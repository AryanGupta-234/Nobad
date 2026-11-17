"""Folder sync for the web UI, on the existing planner, conflict resolver, executor and baseline service.

How a sync runs:
1. **Preview** (dry run). Both folders are listed (the local one without following links, the server one folder by
   folder) and ``SyncPlanner`` decides each file: copy up, copy down, replace, delete, conflict, or leave alone.
   Two-way jobs compare against the baseline saved after the last successful sync, so a file changed on one side only
   is copied, and a file deleted on one side only is deleted on the other. Files that differ on both sides are
   conflicts; for those, checksums are compared first so files that only differ in time stamps aren't flagged.
   Nothing is changed by a preview. Its result is kept under a token for 15 minutes.
2. **Decide**: every conflict needs a choice (keep mine, keep the server's, keep both, skip). Choices that make no
   sense for a file, such as "keep mine" when the file was deleted here, are refused.
3. **Run**: the plan is built again first. If anything changed since the preview, nothing runs and the page gets the
   new preview to check. Otherwise copies go through the transfer queue (visible in the Transfers dock) and deletes
   run only after every copy finished. Replacing or deleting files needs an explicit confirmation. After a
   successful run of a saved job, a new baseline is saved.

Paths from the server are joined only from plain names (``is_unsafe_entry_name``); the executor also checks every
target with ``safe_destination`` / ``is_path_traversal``."""
from __future__ import annotations

import asyncio
import hashlib
import os
import posixpath
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app_web import bus, tasks
from app_web.files import FileError, run_sync
from editor.encoding import detect_encoding, is_probably_binary
from editor.syntax import language_for_path
from file_ops.safety import is_unsafe_entry_name
from sync.baseline_service import SyncBaselineService
from sync.conflicts import SyncConflictChoice, SyncConflictDecision, SyncConflictResolver
from sync.diff_engine import SyncAction, SyncManifestEntry, SyncPreview
from sync.ignore_rules import DEFAULT_IGNORE_PATTERNS, should_ignore
from sync.sync_executor import SyncExecutionPolicy, SyncExecutor
from sync.sync_job import SyncJob, SyncMode
from sync.sync_planner import SyncPlanner

MODES = {m.value: m for m in (SyncMode.LOCAL_TO_REMOTE, SyncMode.REMOTE_TO_LOCAL, SyncMode.TWO_WAY)}
CHOICES = {c.value: c for c in SyncConflictChoice}
MAX_FILES = 200_000
PLAN_TTL = 15 * 60
DIFF_LIMIT = 2 * 1024 * 1024
PREVIEW_KEY, RUN_KEY = "sync.preview", "sync.run"


class SyncError(FileError):
    pass


class _Cancelled(Exception):
    pass


@dataclass
class Plan:
    token: str
    job: SyncJob
    preview: SyncPreview
    local: dict[str, SyncManifestEntry]
    remote: dict[str, SyncManifestEntry]
    connection: Any
    saved: bool
    created: float


# ---------------------------------------------------------------- job specs
def _text(value: Any, label: str, *, limit: int = 4096, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        raise SyncError(f"{label} isn't valid.")
    value = value.strip()
    if required and not value:
        raise SyncError(f"Enter the {label.lower()}.")
    return value


def parse_ignore(value: Any) -> list[str]:
    if value is None:
        return list(DEFAULT_IGNORE_PATTERNS)
    if isinstance(value, str):
        value = value.replace("\n", ",").split(",")
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SyncError("Skip names must be text.")
    names = [v.strip() for v in value if v.strip()]
    if len(names) > 200 or any(len(n) > 255 or "/" in n or "\\" in n for n in names):
        raise SyncError("Skip names are plain file or folder names, like node_modules or .git.")
    return names


def local_root(job: SyncJob) -> str:
    return job.destination_path if job.mode == SyncMode.REMOTE_TO_LOCAL else job.source_path


def remote_root(job: SyncJob) -> str:
    return job.source_path if job.mode == SyncMode.REMOTE_TO_LOCAL else job.destination_path


def job_summary(job: SyncJob) -> dict[str, Any]:
    return {"id": job.id, "name": job.name, "mode": job.mode.value, "local": local_root(job), "remote": remote_root(job),
            "ignore": list(job.ignore_patterns), "profile_id": job.profile_id}


# ---------------------------------------------------------------- manifests
def local_manifest(root: Path, patterns: list[str] | None, cancelled: threading.Event) -> list[SyncManifestEntry]:
    """Every regular file under ``root``. Links are skipped (never followed); skipped names prune whole folders."""
    entries: list[SyncManifestEntry] = []
    for folder, dirs, files in os.walk(root, followlinks=False):
        if cancelled.is_set():
            raise _Cancelled()
        rel_folder = Path(folder).relative_to(root).as_posix()
        rel_folder = "" if rel_folder == "." else rel_folder
        dirs[:] = [d for d in dirs if not should_ignore(f"{rel_folder}/{d}" if rel_folder else d, patterns)
                   and not os.path.islink(os.path.join(folder, d))]
        for name in files:
            rel = f"{rel_folder}/{name}" if rel_folder else name
            full = os.path.join(folder, name)
            if should_ignore(rel, patterns) or os.path.islink(full):
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            entries.append(SyncManifestEntry(path=rel, size=st.st_size,
                                             modified_at=datetime.fromtimestamp(st.st_mtime, timezone.utc)))
            if len(entries) > MAX_FILES:
                raise SyncError(f"The local folder has more than {MAX_FILES:,} files. Choose a smaller folder.")
    return entries


async def remote_manifest(ops: Any, root: str, patterns: list[str] | None, cancelled: threading.Event) -> list[SyncManifestEntry]:
    entries: list[SyncManifestEntry] = []
    stack: list[tuple[str, str]] = [("", root or ".")]
    folders = 0
    while stack:
        if cancelled.is_set():
            raise _Cancelled()
        rel, path = stack.pop()
        result = await ops.list_dir(path, show_hidden=True)
        if not result.ok:
            raise SyncError(f"Couldn't read {path} on the server: {result.message}")
        folders += 1
        if folders % 25 == 0:
            bus.broadcast("sync.progress", {"phase": "remote", "folders": folders, "files": len(entries)})
        for item in result.data or []:
            if is_unsafe_entry_name(item.name):
                continue
            child = f"{rel}/{item.name}" if rel else item.name
            if should_ignore(child, patterns):
                continue
            if item.is_dir:
                stack.append((child, posixpath.join(path, item.name)))
            elif item.is_file:
                entries.append(SyncManifestEntry(path=child, size=item.size, modified_at=item.modified_at))
                if len(entries) > MAX_FILES:
                    raise SyncError(f"The server folder has more than {MAX_FILES:,} files. Choose a smaller folder.")
    return entries


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _signature(preview: SyncPreview) -> set[tuple[Any, ...]]:
    return {(e.path, e.action.value, e.source_size, e.destination_size) for e in preview.entries}


def allowed_choices(path: str, local: dict[str, Any], remote: dict[str, Any]) -> set[str]:
    """Which conflict choices can actually be carried out for this file."""
    here, there = path in local, path in remote
    if here and there:
        return set(CHOICES)
    if here:                                            # gone on the server, changed here
        return {"use_local", "skip"}
    if there:                                           # gone here, changed on the server
        return {"use_remote", "skip"}
    return {"skip"}


def replaces(entry: Any, local: dict[str, Any], remote: dict[str, Any]) -> bool:
    """True when carrying out this entry overwrites a file that exists now (the listings decide, not the sizes)."""
    if entry.action == SyncAction.KEEP_BOTH:
        return True
    if entry.action in {SyncAction.UPLOAD, SyncAction.OVERWRITE}:
        return entry.path in remote
    if entry.action == SyncAction.DOWNLOAD:
        return entry.path in local
    return False


def counts(preview: SyncPreview, local: dict[str, Any], remote: dict[str, Any]) -> dict[str, int]:
    c = {"upload": 0, "download": 0, "replace": 0, "delete": len(preview.deletes), "conflict": len(preview.conflicts),
         "same": len(preview.skipped), "bytes": preview.total_size}
    for e in preview.entries:
        if e.action in {SyncAction.UPLOAD, SyncAction.OVERWRITE, SyncAction.DOWNLOAD, SyncAction.KEEP_BOTH}:
            if replaces(e, local, remote):
                c["replace"] += 1
            else:
                c["upload" if e.action != SyncAction.DOWNLOAD else "download"] += 1
    return c


def needs_confirmation(preview: SyncPreview, local: dict[str, Any], remote: dict[str, Any]) -> bool:
    c = counts(preview, local, remote)
    return bool(c["replace"] or c["delete"])


# ---------------------------------------------------------------- service
class SyncService:
    def __init__(self, app_data: Any, session: Any, transfers: Any) -> None:
        self.app_data = app_data
        self.session = session
        self.transfers = transfers
        self.planner = SyncPlanner()
        self.executor = SyncExecutor()
        self.resolver = SyncConflictResolver()
        self.baselines = SyncBaselineService(app_data.session_factory)
        self._plans: dict[str, Plan] = {}
        self._cancel = threading.Event()
        session.on_closed.append(lambda _profile_id: self._plans.clear())

    # ---- saved jobs
    def jobs(self) -> list[dict[str, Any]]:
        with self.app_data.session_factory() as s:
            return [job_summary(j) for j in self.app_data.sync_jobs(s).list()]

    def _saved(self, job_id: Any) -> SyncJob | None:
        if not isinstance(job_id, str) or not job_id:
            return None
        with self.app_data.session_factory() as s:
            return next((j for j in self.app_data.sync_jobs(s).list() if j.id == job_id), None)

    def build_job(self, spec: Any) -> tuple[SyncJob, bool]:
        if not isinstance(spec, dict):
            raise SyncError("Fill in the sync job.")
        mode = MODES.get(spec.get("mode"))
        if mode is None:
            raise SyncError("Choose which way to sync.")
        local = _text(spec.get("local"), "Folder on this computer")
        remote = _text(spec.get("remote"), "Folder on the server")
        saved = self._saved(spec.get("id"))
        current = self.session.current
        profile_id = current.profile.id if current is not None else (saved.profile_id if saved else None)
        if saved and saved.profile_id and saved.profile_id != profile_id and self.session.find_profile(saved.profile_id):
            profile_id = saved.profile_id           # stays with its saved server; _connection refuses another one
        job = SyncJob(
            id=saved.id if saved else str(uuid4()),
            name=_text(spec.get("name"), "Name", limit=120, required=False) or "Untitled sync",
            mode=mode,
            source_path=remote if mode == SyncMode.REMOTE_TO_LOCAL else local,
            destination_path=local if mode == SyncMode.REMOTE_TO_LOCAL else remote,
            ignore_patterns=parse_ignore(spec.get("ignore")),
            profile_id=profile_id,
            checksum_policy=saved.checksum_policy if saved else "ambiguous",
            conflict_suffix=saved.conflict_suffix if saved else "remote-conflict",
        )
        return job, saved is not None

    def save(self, spec: Any) -> dict[str, Any]:
        job, _was_saved = self.build_job(spec)
        if not Path(local_root(job)).expanduser().is_dir():
            raise SyncError(f"{local_root(job)} isn't a folder on this computer.")
        with self.app_data.session_factory() as s:
            self.app_data.sync_jobs(s).add(job)
            s.commit()
        bus.log(f"Sync job saved: {job.name}", "ok", "sync")
        return job_summary(job)

    def delete(self, job_id: Any) -> None:
        if not isinstance(job_id, str) or self._saved(job_id) is None:
            raise SyncError("That sync job no longer exists.")
        from storage.models import SyncBaselineEntryModel, SyncBaselineModel

        with self.app_data.session_factory() as s:          # the baseline rows reference the job: remove them first
            for base in s.query(SyncBaselineModel).filter_by(job_id=job_id).all():
                s.query(SyncBaselineEntryModel).filter_by(baseline_id=base.id).delete()
                s.delete(base)
            s.flush()
            self.app_data.sync_jobs(s).delete(job_id)
            s.commit()

    # ---- preview
    def _connection(self, job: SyncJob) -> Any:
        current = self.session.current
        if current is None:
            raise SyncError("Connect to the server first.")
        if job.profile_id and current.profile.id != job.profile_id:
            owner = self.session.find_profile(job.profile_id)
            if owner is not None:
                raise SyncError(f"This sync job belongs to {owner.name or owner.host}. Connect to it first.")
        return current

    def _baseline(self, job: SyncJob) -> Any:
        """The last successful state, only if it was taken for these same folders on this same server."""
        if job.mode != SyncMode.TWO_WAY:
            return None
        base = self.baselines.get(job.id)
        if base is None or base.local_root != local_root(job) or base.remote_root != remote_root(job):
            return None
        if base.profile_id and base.profile_id != job.profile_id:
            return None
        return base

    async def _build(self, job: SyncJob, connection: Any) -> tuple[SyncPreview, dict, dict]:
        ops = connection.file_operations()
        root = Path(local_root(job)).expanduser()
        if not root.is_dir():
            raise SyncError(f"{root} isn't a folder on this computer.")
        patterns = job.ignore_patterns or None
        bus.broadcast("sync.progress", {"phase": "local", "files": 0})
        local = await asyncio.to_thread(local_manifest, root, patterns, self._cancel)
        bus.broadcast("sync.progress", {"phase": "remote", "files": 0, "folders": 0})
        remote = await remote_manifest(ops, remote_root(job), patterns, self._cancel)
        baseline = await asyncio.to_thread(self._baseline, job)

        def plan() -> SyncPreview:
            if job.mode == SyncMode.REMOTE_TO_LOCAL:
                return self.planner.preview_from_manifests(job, remote, local)
            return self.planner.preview_from_manifests(job, local, remote, baseline)

        preview = plan()
        if job.mode == SyncMode.TWO_WAY and preview.conflicts and job.checksum_policy == "ambiguous":
            bus.broadcast("sync.progress", {"phase": "checksums", "files": len(preview.conflicts)})
            local, remote = await self._checksums(root, ops, remote_root(job), local, remote, set(preview.conflicts))
            preview = plan()
        return preview, {e.path: e for e in local}, {e.path: e for e in remote}

    async def _checksums(self, root: Path, ops: Any, rroot: str, local: list, remote: list, paths: set[str]) -> tuple[list, list]:
        """Checksums only where sizes match: different sizes can't be the same file anyway."""
        sizes = {e.path: e.size for e in remote}
        new_local, new_remote = [], []
        same_size = {e.path for e in local if e.path in paths and sizes.get(e.path) == e.size}
        for e in local:
            if e.path in same_size:
                e = replace(e, checksum=await asyncio.to_thread(_sha256, root / e.path))
            new_local.append(e)
        for e in remote:
            if e.path in same_size and hasattr(ops, "calculate_checksum"):
                result = await ops.calculate_checksum(posixpath.join(rroot, e.path))
                if result.ok:
                    e = replace(e, checksum=result.data)
            new_remote.append(e)
        return new_local, new_remote

    def start_preview(self, spec: Any) -> bool:
        job, saved = self.build_job(spec)
        connection = self._connection(job)
        if tasks.is_running(RUN_KEY):
            raise SyncError("A sync is running. Wait for it to finish.")
        self._cancel.clear()

        async def work() -> None:
            started = time.monotonic()
            try:
                preview, local, remote = await self._build(job, connection)
            except _Cancelled:
                bus.broadcast("sync.preview", {"cancelled": True})
                return
            self._publish(Plan(secrets.token_urlsafe(16), job, preview, local, remote, connection, saved, time.monotonic()),
                           seconds=time.monotonic() - started)

        return tasks.run_task(PREVIEW_KEY, work)

    def cancel_preview(self) -> None:
        self._cancel.set()

    def _publish(self, plan: Plan, *, seconds: float = 0, changed: bool = False) -> None:
        now = time.monotonic()
        for token in [t for t, p in self._plans.items() if now - p.created > PLAN_TTL]:
            del self._plans[token]
        self._plans[plan.token] = plan
        c = counts(plan.preview, plan.local, plan.remote)
        bus.log(f"Sync preview for {plan.job.name}: {c['upload']} up, {c['download']} down, {c['replace']} to replace, "
                f"{c['delete']} to delete, {c['conflict']} conflicts.", "info", "sync")
        bus.broadcast("sync.preview", {"token": plan.token, "job": job_summary(plan.job), "counts": c,
                                       "needs_confirm": needs_confirmation(plan.preview, plan.local, plan.remote), "baseline": self._has_baseline(plan),
                                       "saved": plan.saved, "seconds": round(seconds, 1), "changed": changed})

    def _has_baseline(self, plan: Plan) -> bool:
        return plan.saved and self._baseline(plan.job) is not None

    def _plan(self, token: Any) -> Plan:
        plan = self._plans.get(token) if isinstance(token, str) else None
        if plan is None or time.monotonic() - plan.created > PLAN_TTL:
            raise SyncError("This preview is out of date. Preview again.")
        if self.session.current is not plan.connection:
            raise SyncError("The connection changed since the preview. Preview again.")
        return plan

    def entries(self, token: Any) -> list[dict[str, Any]]:
        plan = self._plan(token)
        rows = []
        for e in plan.preview.entries:
            row: dict[str, Any] = {"path": e.path, "action": e.action.value, "reason": e.reason,
                                   "src": e.source_size, "dst": e.destination_size,
                                   "target": e.target_side.value if e.target_side else None}
            if replaces(e, plan.local, plan.remote):
                row["replaces"] = True
            if e.action == SyncAction.CONFLICT:
                row["choices"] = sorted(allowed_choices(e.path, plan.local, plan.remote))
                local, remote = plan.local.get(e.path), plan.remote.get(e.path)
                row["local_time"] = local.modified_at.isoformat() if local and local.modified_at else None
                row["remote_time"] = remote.modified_at.isoformat() if remote and remote.modified_at else None
            rows.append(row)
        return rows

    # ---- compare one conflict
    def compare(self, token: Any, path: Any) -> dict[str, Any]:
        plan = self._plan(token)
        if not isinstance(path, str) or path not in plan.local or path not in plan.remote:
            raise SyncError("Only files that exist on both sides can be compared.")
        local_file = Path(local_root(plan.job)).expanduser() / path
        ops = plan.connection.file_operations()

        async def load() -> dict[str, Any]:
            if not local_file.is_file() or local_file.stat().st_size > DIFF_LIMIT or is_probably_binary(local_file):
                raise SyncError("Compare works for text files up to 2 MB.")
            with tempfile.TemporaryDirectory(prefix="nbfb-sync-diff-") as folder:
                copy = Path(folder) / "server-copy"
                result = await ops.download_file(posixpath.join(remote_root(plan.job), path), copy)
                if not result.ok:
                    raise SyncError(result.message)
                if copy.stat().st_size > DIFF_LIMIT or is_probably_binary(copy):
                    raise SyncError("Compare works for text files up to 2 MB.")
                theirs = copy.read_text(encoding=detect_encoding(copy), errors="replace")
            mine = local_file.read_text(encoding=detect_encoding(local_file), errors="replace")
            return {"local": mine, "remote": theirs, "language": language_for_path(path, mine[:200], mine[:2000])}

        return run_sync(load(), timeout=120)

    # ---- run
    def start_run(self, token: Any, decisions: Any, confirmed: Any) -> bool:
        plan = self._plan(token)
        if tasks.is_running(PREVIEW_KEY):
            raise SyncError("A preview is still being built.")
        if decisions is None:
            decisions = {}
        if not isinstance(decisions, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in decisions.items()):
            raise SyncError("Conflict choices aren't valid.")
        missing = [p for p in plan.preview.conflicts if p not in decisions]
        if missing:
            raise SyncError(f"Choose what to do with {len(missing)} conflicting file{'s' if len(missing) != 1 else ''} first.")
        chosen = []
        for path in plan.preview.conflicts:
            choice = decisions[path]
            if choice not in allowed_choices(path, plan.local, plan.remote):
                raise SyncError(f"That choice isn't possible for {path}.")
            chosen.append(SyncConflictDecision(path, CHOICES[choice]))
        resolved = self.resolver.resolve(plan.preview, chosen, suffix=plan.job.conflict_suffix).preview
        if needs_confirmation(resolved, plan.local, plan.remote) and confirmed is not True:
            raise SyncError("This sync replaces or deletes files. Confirm it first.")

        async def work() -> None:
            self._plans.pop(plan.token, None)
            self._cancel.clear()
            fresh, local, remote = await self._build(plan.job, plan.connection)
            if _signature(fresh) != _signature(plan.preview):
                bus.log("Files changed since the preview; nothing was synced. Check the new preview.", "warn", "sync")
                self._publish(Plan(secrets.token_urlsafe(16), plan.job, fresh, local, remote, plan.connection, plan.saved,
                                   time.monotonic()), changed=True)
                return
            ops = plan.connection.file_operations()
            # The confirmation gate is the check above, which reads the listings. The executor's own check goes by
            # sizes and would also stop every new download in a two-way sync, so it is told the user confirmed.
            result = await self.executor.execute(plan.job, resolved, ops, self.transfers.manager,
                                                 policy=SyncExecutionPolicy(destructive_confirmed=True))
            baseline = False
            if result.ok and plan.saved:
                baseline = await self._save_baseline(plan, resolved, ops)
            data = result.data
            payload = {"ok": result.ok, "message": bus.scrub(result.message), "job": job_summary(plan.job),
                       "baseline": baseline,
                       "copied": getattr(data, "queued_transfers", 0), "deleted_local": getattr(data, "local_deletes", 0),
                       "deleted_remote": getattr(data, "remote_deletes", 0)}
            bus.log(f"Sync {plan.job.name}: {result.message}", "ok" if result.ok else "error", "sync")
            bus.broadcast("sync.result", payload)

        return tasks.run_task(RUN_KEY, work)

    async def _save_baseline(self, plan: Plan, resolved: SyncPreview, ops: Any) -> bool:
        """The baseline is what both sides look like now, read again after the run (never assumed)."""
        try:
            patterns = plan.job.ignore_patterns or None
            local = await asyncio.to_thread(local_manifest, Path(local_root(plan.job)).expanduser(), patterns, threading.Event())
            remote = await remote_manifest(ops, remote_root(plan.job), patterns, threading.Event())
        except (SyncError, _Cancelled, OSError) as exc:
            bus.log(f"Sync finished, but the new baseline couldn't be read: {exc}", "warn", "sync")
            return False
        keep = {e.path for e in resolved.entries if e.action == SyncAction.SKIP and e.reason.startswith("Conflict skipped")}
        await asyncio.to_thread(self.baselines.save, job=plan.job, local_entries=local, remote_entries=remote,
                                preserve_paths=keep)
        return True
