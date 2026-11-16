"""Uploads and downloads for the web UI, on the existing TransferManager.

* ``plan`` finds which items already exist at the destination, so the page can ask once (Overwrite / Skip / Rename,
  for the whole batch) before anything starts.
* ``start`` queues the items with that decision. Without a conflict the policy stays "ask", which makes a file that
  appears meanwhile fail safely instead of being overwritten (TransferManager raises on ask).
* Job updates fire on the asyncio thread; they go through a Coalescer, so the page gets at most one update per job
  every 100 ms, however fast the transfer is.
* Download targets go through ``safe_destination`` (issue #29); upload names come from the local file system."""
from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Any

from app_web import bus
from app_web.files import FileError, run_sync
from core.async_runtime import AsyncRuntime
from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from file_ops.safety import safe_destination
from transfers.transfer_job import TransferDirection, TransferJob, TransferStatus
from transfers.transfer_manager import TransferManager, default_conflict_decision

POLICIES = {"overwrite": ConflictPolicy.OVERWRITE, "skip": ConflictPolicy.SKIP, "rename": ConflictPolicy.RENAME}
MAX_ITEMS = 2000


def job_summary(job: TransferJob) -> dict[str, Any]:
    upload = job.direction == TransferDirection.LOCAL_TO_SERVER
    source = job.source_path
    name = Path(source).name if upload else posixpath.basename(source)
    total = job.bytes_total if job.bytes_total is not None else job.size
    return {
        "id": job.id, "batch": job.batch_id, "name": name, "dir": "up" if upload else "down",
        "src": source, "dst": job.destination_path, "status": job.status.value,
        "done": job.bytes_done, "total": total, "progress": round(job.progress, 4),
        "speed": job.speed, "eta": job.eta_seconds, "error": bus.scrub(job.error_message) if job.error_message else None,
        "retries": job.retry_count,
    }


class TransferService:
    def __init__(self, max_concurrent: int = 3) -> None:
        self.manager = TransferManager(max_concurrent=max_concurrent)
        self._updates = bus.Coalescer("xfer.jobs", interval=0.1)
        self.manager.job_updated.connect(lambda job: self._updates.push(job.id, job_summary(job)))
        self.manager.log_event.connect(lambda e: bus.log(e.message, _level(e.level), "transfer"))
        self.manager.batch_finished.connect(self._batch_finished)
        self._runner = None

    def _batch_finished(self, batch_id: str) -> None:
        jobs = [j for j in self.manager.queue.jobs if j.batch_id == batch_id]
        failed = sum(1 for j in jobs if j.status == TransferStatus.FAILED)
        done = sum(1 for j in jobs if j.status == TransferStatus.COMPLETED)
        self._updates.flush()
        bus.broadcast("xfer.batch_done", {"batch": batch_id, "done": done, "failed": failed})

    def jobs(self) -> list[dict[str, Any]]:
        return [job_summary(j) for j in self.manager.queue.jobs]

    # ---------------------------------------------------------------- plan
    def plan(self, connection: Any, direction: str, items: list[str], dest: str) -> list[dict[str, str]]:
        ops = _ops(connection)
        _check_items(items)
        conflicts: list[dict[str, str]] = []
        if direction == "upload":
            for local in items:
                remote = posixpath.join(dest, Path(local).name)
                if run_sync(ops.stat(remote)).ok:
                    conflicts.append({"name": Path(local).name, "path": remote})
        elif direction == "download":
            for remote in items:
                target = safe_destination(Path(dest), posixpath.basename(remote.rstrip("/")))
                if target.exists():
                    conflicts.append({"name": target.name, "path": str(target)})
        else:
            raise FileError("Unknown transfer direction.")
        return conflicts

    # ---------------------------------------------------------------- start
    def start(self, connection: Any, direction: str, items: list[str], dest: str, policy: str | None) -> int:
        ops = _ops(connection)
        _check_items(items)
        if direction not in {"upload", "download"}:
            raise FileError("Unknown transfer direction.")
        if policy is not None and policy not in POLICIES:
            raise FileError("Choose overwrite, skip or rename.")
        decision = ConflictDecision(POLICIES[policy], apply_to_all=True) if policy else default_conflict_decision()
        if direction == "download" and not Path(dest).is_dir():
            raise FileError(f"{dest} isn't a folder.")
        # Enqueue on the runtime thread: the scheduler changes the same queue there.
        queued = run_sync(self._enqueue(ops, direction, items, dest, decision))
        self._run()
        return queued

    async def _enqueue(self, ops: Any, direction: str, items: list[str], dest: str, decision: ConflictDecision) -> int:
        queued = 0
        if direction == "upload":
            for local in items:
                source = Path(local)
                remote = posixpath.join(dest, source.name)
                if source.is_dir():
                    queued += len(self.manager.enqueue_upload_folder(ops, local_folder=source, remote_folder=remote,
                                                                     conflict_decision=decision))
                elif source.is_file():
                    self.manager.enqueue_upload_file(ops, local_path=source, remote_path=remote, conflict_decision=decision)
                    queued += 1
                else:
                    raise FileError(f"{source} no longer exists.")
            return queued
        root = Path(dest)
        for remote in items:
            stat = await ops.stat(remote)
            if not stat.ok:
                raise FileError(stat.message)
            item = stat.data
            target = safe_destination(root, posixpath.basename(remote.rstrip("/")))
            if item.is_dir:
                queued += len(await self.manager.enqueue_download_folder(
                    ops, remote_item=item, local_folder=target, conflict_decision=decision))
            else:
                self.manager.enqueue_download_file(ops, remote_item=item, local_path=target, conflict_decision=decision)
                queued += 1
        return queued

    def _run(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = AsyncRuntime.instance().submit(self.manager.run_until_idle())

    # ---------------------------------------------------------------- controls
    def cancel(self, job_id: str) -> Any:
        return run_sync(self.manager.cancel_job(job_id))

    def retry(self, job_id: str) -> Any:
        result = run_sync(self.manager.retry_job(job_id))
        self._run()
        return result

    def retry_failed(self) -> Any:
        result = run_sync(self.manager.retry_failed())
        self._run()
        return result

    def clear_finished(self) -> None:
        async def clear() -> None:
            self.manager.clear_completed()
            self.manager.clear_failed()
            self.manager.queue.clear_cancelled()
        run_sync(clear())
        bus.broadcast("xfer.cleared", {})


def _ops(connection: Any) -> Any:
    if connection is None:
        raise FileError("Not connected to a server.")
    return connection.file_operations()


def _check_items(items: Any) -> None:
    if not isinstance(items, list) or not items or not all(isinstance(i, str) and i for i in items):
        raise FileError("Choose at least one item.")
    if len(items) > MAX_ITEMS:
        raise FileError(f"Choose up to {MAX_ITEMS} items at a time.")


def _level(level: str) -> str:
    return {"error": "bad", "warning": "warn", "success": "ok"}.get(level, "info")
