"""Deployments for the web UI, on the existing planner, executor, history and manual rollback services.

A deployment runs like this (all of it is the existing ``DeploymentExecutor``; this layer adds the window's flow):
1. **Preview**: optional local build (its output streams to the page), then ``DeploymentPlanner.build_preview``:
   what will be uploaded, replaced and (in mirror mode) deleted. Nothing on the server changes. The preview is kept
   under a one-time token for 15 minutes, tied to the connection it was made on.
2. **Deploy**: needs ``confirmed``. The job is saved first (history and backups belong to a saved job). The executor
   takes the server's deployment lock, builds the preview again under the lock and stops if it changed, backs up the
   target, uploads, runs the job's commands and health checks, and rolls back automatically when any step fails.
   Each stage is sent to the page as it starts. A lock left behind by a crashed run can be removed on request.
3. **History**: every run with its stages; backups and releases can be scanned from the server and restored
   (manual rollback, also under the lock, confirmed first).

Deployments need a connection that can run commands (SSH): backups, locks and checks are commands on the server."""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app_web import bus, tasks
from app_web.files import FileError
from app_web.terminals import OutputBuffer
from core.async_runtime import AsyncRuntime
from deployment.deployment_executor import DeploymentExecutor
from deployment.deployment_history import DeploymentHistoryService
from deployment.deployment_job import (
    DeploymentArtifactKind,
    DeploymentExecutionPolicy,
    DeploymentExecutionResult,
    DeploymentJob,
    DeploymentMode,
    DeploymentPreview,
    DeploymentRun,
    DeploymentRunStatus,
    DeploymentStageEvent,
    DeploymentStrategy,
    HealthCheckConfig,
    HealthCheckOrigin,
)
from deployment.deployment_planner import DeploymentPlanner
from deployment.deployment_templates import DEPLOYMENT_TEMPLATES
from deployment.manual_rollback import ManualRollbackService

PLAN_TTL = 15 * 60
PREVIEW_KEY, RUN_KEY, SCAN_KEY = "deploy.preview", "deploy.run", "deploy.scan"


class DeployError(FileError):
    pass


@dataclass
class Plan:
    token: str
    job: DeploymentJob
    preview: DeploymentPreview
    connection: Any
    built: bool
    created: float


# ---------------------------------------------------------------- job specs
def _text(value: Any, label: str, *, limit: int = 4096) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        raise DeployError(f"{label} isn't valid.")
    return value.strip()


def _int(value: Any, label: str, low: int, high: int, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise DeployError(f"{label} must be a whole number.") from None
    if not low <= number <= high:
        raise DeployError(f"{label} must be between {low} and {high}.")
    return number


def _ignore(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace("\n", ",").split(",")
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise DeployError("Skip names must be text.")
    names = [v.strip() for v in value if v.strip()]
    if len(names) > 200 or any(len(n) > 255 or "/" in n or "\\" in n for n in names):
        raise DeployError("Skip names are plain file or folder names, like node_modules or .git.")
    return names


def job_summary(job: DeploymentJob) -> dict[str, Any]:
    h = job.health_check
    return {
        "id": job.id, "name": job.name, "template": job.template, "profile_id": job.profile_id,
        "mode": job.mode.value, "strategy": job.strategy.value,
        "project": job.local_project_folder, "build_folder": job.local_build_folder, "remote": job.remote_target_folder,
        "ignore": list(job.ignore_patterns), "run_build": job.run_local_build, "build_command": job.local_build_command,
        "chmod_enabled": job.chmod_enabled, "chmod_mode": job.chmod_mode, "post_command": job.post_deploy_command,
        "cache_command": job.cache_clear_command, "restart_command": job.restart_command,
        "backup_dir": job.backup_directory, "backup_retention": job.backup_retention,
        "release_retention": job.release_retention,
        "health": {"command": h.command, "url": h.http_url, "origin": h.http_origin.value, "attempts": h.attempts,
                   "timeout": h.timeout_seconds, "interval": h.interval_seconds, "min": h.minimum_status,
                   "max": h.maximum_status, "expect": h.expected_substring, "verify_tls": h.verify_tls},
    }


def commands_of(job: DeploymentJob) -> list[dict[str, str]]:
    steps = [("chmod", f"chmod -R {job.chmod_mode} ." if job.chmod_enabled else ""), ("after_upload", job.post_deploy_command),
             ("cache", job.cache_clear_command), ("restart", job.restart_command)]
    return [{"step": step, "command": command} for step, command in steps if command]


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def run_summary(run: DeploymentRun) -> dict[str, Any]:
    return {"id": run.id, "action": run.action, "status": run.status.value, "started": _iso(run.started_at),
            "finished": _iso(run.finished_at), "seconds": run.duration_seconds, "uploads": run.uploads,
            "overwrites": run.overwrites, "deletes": run.deletes, "bytes": run.bytes_total, "health_ok": run.health_ok,
            "artifact": run.artifact_path, "rolled_back": run.rolled_back,
            "rollback_error": bus.scrub(run.rollback_error) if run.rollback_error else None,
            "message": bus.scrub(run.message), "host": run.host, "target": run.remote_target}


# ---------------------------------------------------------------- service
class DeployService:
    def __init__(self, app_data: Any, session: Any, transfers: Any) -> None:
        self.app_data = app_data
        self.session = session
        self.transfers = transfers
        self.planner = DeploymentPlanner()
        self.executor = DeploymentExecutor(planner=self.planner)
        self.rollbacks = ManualRollbackService()
        self.history = DeploymentHistoryService(app_data)
        self._plans: dict[str, Plan] = {}
        self._output = OutputBuffer(send=lambda _type, payload: bus.broadcast("deploy.output", {"data": payload["data"]}))
        self._preview_cancelled = False
        session.on_closed.append(lambda _profile_id: self._plans.clear())

    # ---- saved jobs
    def templates(self) -> list[dict[str, Any]]:
        return [{"name": t.name, "build_command": t.build_command, "build_folder": t.build_folder,
                 "post_command": t.post_deploy_command, "restart_command": t.restart_command, "ignore": list(t.ignore_patterns)}
                for t in DEPLOYMENT_TEMPLATES]

    def jobs(self) -> list[dict[str, Any]]:
        with self.app_data.session_factory() as s:
            return [job_summary(j) for j in self.app_data.deployment_jobs(s).list()]

    def _saved(self, job_id: Any) -> DeploymentJob | None:
        if not isinstance(job_id, str) or not job_id:
            return None
        with self.app_data.session_factory() as s:
            return next((j for j in self.app_data.deployment_jobs(s).list() if j.id == job_id), None)

    def build_job(self, spec: Any) -> tuple[DeploymentJob, bool]:
        if not isinstance(spec, dict):
            raise DeployError("Fill in the deployment.")
        saved = self._saved(spec.get("id"))
        try:
            mode = DeploymentMode(spec.get("mode") or "upload_only")
            strategy = DeploymentStrategy(spec.get("strategy") or "in_place")
        except ValueError:
            raise DeployError("Choose how files are replaced on the server.") from None
        health = spec.get("health") if isinstance(spec.get("health"), dict) else {}
        try:
            origin = HealthCheckOrigin(health.get("origin") or "desktop")
        except ValueError:
            raise DeployError("Choose where the web address is checked from.") from None
        url = _text(health.get("url"), "Web address", limit=2000)
        if url and not re.match(r"^https?://[^\s/]+", url, re.I):
            raise DeployError("The web address must start with http:// or https://.")
        current = self.session.current
        profile_id = current.profile.id if current is not None else (saved.profile_id if saved else None)
        if saved and saved.profile_id and saved.profile_id != profile_id and self.session.find_profile(saved.profile_id):
            profile_id = saved.profile_id
        chmod_mode = _text(spec.get("chmod_mode"), "Permissions", limit=4) or "755"
        job = DeploymentJob(
            id=saved.id if saved else str(uuid4()),
            name=_text(spec.get("name"), "Name", limit=120) or "Untitled deployment",
            template=_text(spec.get("template"), "Template", limit=80) or "Generic Folder",
            local_build_folder=_text(spec.get("build_folder"), "Folder to upload"),
            remote_target_folder=_text(spec.get("remote"), "Folder on the server"),
            options=dict(saved.options) if saved else {},
            profile_id=profile_id,
            mode=mode,
            strategy=strategy,
            local_project_folder=_text(spec.get("project"), "Project folder"),
            ignore_patterns=_ignore(spec.get("ignore")),
            run_local_build=bool(spec.get("run_build")),
            local_build_command=_text(spec.get("build_command"), "Build command", limit=2000),
            chmod_enabled=bool(spec.get("chmod_enabled")),
            chmod_mode=chmod_mode,
            post_deploy_command=_text(spec.get("post_command"), "Command after upload", limit=2000),
            cache_clear_command=_text(spec.get("cache_command"), "Cache command", limit=2000),
            restart_command=_text(spec.get("restart_command"), "Restart command", limit=2000),
            backup_directory=_text(spec.get("backup_dir"), "Backup folder"),
            backup_retention=_int(spec.get("backup_retention"), "Backups to keep", 1, 50, 5),
            release_retention=_int(spec.get("release_retention"), "Releases to keep", 1, 50, 5),
            health_check=HealthCheckConfig(
                command=_text(health.get("command"), "Check command", limit=2000),
                http_url=url, http_origin=origin,
                attempts=_int(health.get("attempts"), "Attempts", 1, 10, 3),
                timeout_seconds=_int(health.get("timeout"), "Timeout", 1, 300, 10),
                interval_seconds=_int(health.get("interval"), "Wait between attempts", 0, 60, 2),
                minimum_status=_int(health.get("min"), "Lowest good status", 100, 599, 200),
                maximum_status=_int(health.get("max"), "Highest good status", 100, 599, 399),
                expected_substring=_text(health.get("expect"), "Expected text", limit=500),
                verify_tls=health.get("verify_tls") is not False,
            ),
            stale_lock_seconds=saved.stale_lock_seconds if saved else 7200,
            history_retention=saved.history_retention if saved else 100,
        )
        if not job.local_build_folder:
            raise DeployError("Choose the folder to upload.")
        if not job.remote_target_folder:
            raise DeployError("Enter the folder on the server.")
        if job.run_local_build and not job.local_project_folder:
            job.local_project_folder = job.local_build_folder
        return job, saved is not None

    def _validate(self, job: DeploymentJob) -> None:
        result = self.planner.validate(job)
        if not result.ok:
            raise DeployError(result.message)

    def save(self, spec: Any) -> dict[str, Any]:
        job, _ = self.build_job(spec)
        self._validate(job)
        self._store(job)
        bus.log(f"Deployment saved: {job.name}", "ok", "deploy")
        return job_summary(job)

    def _store(self, job: DeploymentJob) -> None:
        with self.app_data.session_factory() as s:
            self.app_data.deployment_jobs(s).add(job)
            s.commit()

    def delete(self, job_id: Any) -> None:
        if self._saved(job_id) is None:
            raise DeployError("That deployment no longer exists.")
        with self.app_data.session_factory() as s:
            self.app_data.deployment_jobs(s).delete(job_id)
            s.commit()

    # ---- connection
    def _connection(self, job: DeploymentJob) -> Any:
        current = self.session.current
        if current is None:
            raise DeployError("Connect to the server first.")
        if job.profile_id and current.profile.id != job.profile_id:
            owner = self.session.find_profile(job.profile_id)
            if owner is not None:
                raise DeployError(f"This deployment belongs to {owner.name or owner.host}. Connect to it first.")
        caps = getattr(current, "capabilities", None)
        if caps is not None and not caps.can_exec_command:
            raise DeployError("Deployments need an SSH connection: backups, locks and checks run as commands on the server.")
        return current

    def _busy(self) -> None:
        for key in (PREVIEW_KEY, RUN_KEY, SCAN_KEY):
            if tasks.is_running(key):
                raise DeployError("A deployment task is still running. Wait for it, or cancel it.")

    # ---- preview
    def start_preview(self, spec: Any) -> bool:
        job, saved = self.build_job(spec)
        self._validate(job)
        connection = self._connection(job)
        self._busy()
        self._preview_cancelled = False

        async def work() -> None:
            started = time.monotonic()
            built = False
            if job.run_local_build:
                bus.broadcast("deploy.stage", {"stage": "building", "message": "Running the build on this computer.", "level": "info", "phase": "preview"})
                result = await self.executor.build_runner.run(job.local_build_command, working_directory=job.resolved_project_folder(),
                                                              on_output=lambda line: self._output.push("build", line + "\n"))
                self._output.flush()
                if self._preview_cancelled:
                    bus.broadcast("deploy.preview", {"cancelled": True})
                    return
                if not result.ok:
                    raise DeployError(result.message)
                built = True
            bus.broadcast("deploy.stage", {"stage": "previewing", "message": "Comparing with the server.", "level": "info", "phase": "preview"})
            result = await self.planner.build_preview(job, connection.file_operations())
            if not result.ok:
                raise DeployError(result.message)
            if self._preview_cancelled:
                bus.broadcast("deploy.preview", {"cancelled": True})
                return
            self._publish(Plan(secrets.token_urlsafe(16), job, result.data, connection, built, time.monotonic()), saved,
                          time.monotonic() - started)

        return tasks.run_task(PREVIEW_KEY, work)

    def _publish(self, plan: Plan, saved: bool, seconds: float) -> None:
        now = time.monotonic()
        for token in [t for t, p in self._plans.items() if now - p.created > PLAN_TTL]:
            del self._plans[token]
        self._plans[plan.token] = plan
        p = plan.preview
        bus.broadcast("deploy.preview", {
            "token": plan.token, "job": job_summary(plan.job), "saved": saved, "seconds": round(seconds, 1),
            "counts": {"upload": p.uploads, "replace": p.overwrites, "delete": p.deletes, "bytes": p.bytes_total,
                       "same": len(p.sync_preview.skipped)},
            "target_exists": p.target_exists, "backup": p.backup_archive_path if p.target_exists else None,
            "remote_root": p.remote_root, "commands": commands_of(plan.job),
            "health": {"command": bool(plan.job.health_check.command), "url": plan.job.health_check.http_url or None,
                       "origin": plan.job.health_check.http_origin.value},
            "built": plan.built,
        })

    def _plan(self, token: Any) -> Plan:
        plan = self._plans.get(token) if isinstance(token, str) else None
        if plan is None or time.monotonic() - plan.created > PLAN_TTL:
            raise DeployError("This preview is out of date. Preview again.")
        if self.session.current is not plan.connection:
            raise DeployError("The connection changed since the preview. Preview again.")
        return plan

    def entries(self, token: Any) -> list[dict[str, Any]]:
        plan = self._plan(token)
        return [{"path": e.path, "action": e.action.value, "reason": e.reason, "src": e.source_size, "dst": e.destination_size}
                for e in plan.preview.sync_preview.entries]

    def cancel(self) -> None:
        self._preview_cancelled = True
        AsyncRuntime.instance().submit(self.executor.cancel(self.transfers.manager))

    # ---- deploy
    def _start_run(self, job: DeploymentJob, connection: Any, action: str) -> str:
        profile = connection.profile
        run = DeploymentRun(job_id=job.id, profile_id=job.profile_id, profile_name=profile.name, host=profile.host,
                            remote_target=job.remote_target_folder, strategy=job.strategy, action=action)
        self.history.start_run(run)
        return run.id

    def _on_stage(self, event: DeploymentStageEvent) -> None:
        bus.broadcast("deploy.stage", {"stage": event.stage.value, "message": bus.scrub(event.message), "level": event.level,
                                       "run": event.run_id, "phase": "run"})

    def start_run(self, token: Any, confirmed: Any, break_stale_lock: Any = False) -> bool:
        plan = self._plan(token)
        if confirmed is not True:
            raise DeployError("Confirm the deployment first.")
        self._busy()
        self._store(plan.job)                          # history rows and backups belong to a saved job
        run_id = self._start_run(plan.job, plan.connection, "deploy")

        async def work() -> None:
            result = await self.executor.execute(
                plan.job, plan.preview, plan.connection, plan.connection.file_operations(), self.transfers.manager,
                policy=DeploymentExecutionPolicy(confirmed=True, rollback_on_failure=True, break_stale_lock=break_stale_lock is True),
                build_already_completed=plan.built, run_id=run_id, history_service=self.history, on_stage=self._on_stage,
                on_build_output=lambda line: self._output.push("build", line + "\n"))
            self._output.flush()
            data = result.data if isinstance(result.data, DeploymentExecutionResult) else None
            stale = isinstance(result.data, dict) and bool(result.data.get("stale_lock"))
            changed = bool(data and data.preview_changed)
            if result.ok or changed:
                self._plans.pop(plan.token, None)        # used up: a changed plan has to be previewed again
            payload = self._result_payload(result, data, kind="deploy", job=plan.job)
            payload.update({"stale_lock": stale, "preview_changed": changed, "token": None if (result.ok or changed) else plan.token})
            bus.log(f"Deployment {plan.job.name}: {result.message}", "ok" if result.ok else "error", "deploy")
            bus.broadcast("deploy.result", payload)

        return tasks.run_task(RUN_KEY, work)

    def _result_payload(self, result: Any, data: DeploymentExecutionResult | None, *, kind: str, job: DeploymentJob) -> dict[str, Any]:
        health = data.health_check if data else None
        return {
            "kind": kind, "ok": result.ok, "message": bus.scrub(result.message), "job_id": job.id,
            "details": bus.scrub(result.technical_details) if result.technical_details else None,
            "fix": bus.scrub(result.suggested_fix) if result.suggested_fix else None,
            "cancelled": bool(data and data.cancelled), "rolled_back": bool(data and data.rolled_back),
            "rollback_error": bus.scrub(data.rollback_error) if data and data.rollback_error else None,
            "uploads": data.uploads if data else 0, "overwrites": data.overwrites if data else 0,
            "deletes": data.deletes if data else 0, "backup": data.backup_path if data else None,
            "release": data.release_path if data else None,
            "health": {"ok": health.ok, "message": bus.scrub(health.message), "status": health.status_code} if health else None,
        }

    # ---- history, artifacts, manual rollback
    def history_of(self, job_id: Any) -> dict[str, Any]:
        job = self._saved(job_id)
        if job is None:
            return {"runs": [], "artifacts": []}
        return {"runs": [run_summary(r) for r in self.history.list_runs(job.id, limit=job.history_retention)],
                "artifacts": [{"id": a.id, "kind": a.kind.value, "path": a.path, "format": a.format, "active": a.active,
                               "created": _iso(a.created_at), "imported": a.imported, "size": a.metadata.get("size")}
                              for a in self.history.list_artifacts(job.id)]}

    def stages(self, run_id: Any) -> list[dict[str, Any]]:
        if not isinstance(run_id, str):
            raise DeployError("Unknown run.")
        out = []
        for st in self.history.list_stages(run_id):
            seconds = (st.finished_at - st.started_at).total_seconds() if st.finished_at else None
            out.append({"stage": st.stage.value, "message": bus.scrub(st.message), "level": st.level,
                        "seconds": round(max(0.0, seconds), 2) if seconds is not None else None,
                        "output": bus.scrub(st.output_excerpt) if st.output_excerpt else ""})
        return out

    def start_scan(self, job_id: Any) -> bool:
        job = self._saved(job_id)
        if job is None:
            raise DeployError("Save the deployment first.")
        connection = self._connection(job)
        self._busy()

        async def work() -> None:
            result = await self.rollbacks.scan_artifacts(job, connection)
            if not result.ok:
                raise DeployError(result.message)
            for artifact in result.data or []:
                self.history.add_artifact(artifact)
            bus.broadcast("deploy.history", {"job_id": job.id})

        return tasks.run_task(SCAN_KEY, work)

    def start_rollback(self, job_id: Any, artifact_id: Any, confirmed: Any, break_stale_lock: Any = False) -> bool:
        job = self._saved(job_id)
        if job is None:
            raise DeployError("Save the deployment first.")
        artifact = next((a for a in self.history.list_artifacts(job.id) if a.id == artifact_id), None)
        if artifact is None:
            raise DeployError("That backup or release is no longer listed. Scan the server again.")
        if artifact.active:
            raise DeployError("That release is already the live one.")
        expected = DeploymentArtifactKind.RELEASE if job.strategy == DeploymentStrategy.ATOMIC_RELEASE else DeploymentArtifactKind.BACKUP
        if artifact.kind != expected:
            raise DeployError("This deployment restores " + ("releases" if expected == DeploymentArtifactKind.RELEASE else "backups") + ".")
        if confirmed is not True:
            raise DeployError("Confirm the rollback first.")
        connection = self._connection(job)
        self._busy()
        run_id = self._start_run(job, connection, "manual_rollback")

        async def work() -> None:
            try:
                result = await self.rollbacks.rollback(job, artifact, connection, run_id=run_id, break_stale_lock=break_stale_lock is True,
                                                       history_service=self.history, on_stage=self._on_stage)
            except Exception as exc:
                self.history.finish_run(run_id, status=DeploymentRunStatus.FAILED, message=str(exc), retention=job.history_retention)
                raise
            data = result.data if isinstance(result.data, DeploymentExecutionResult) else None
            stale = isinstance(result.data, dict) and bool(result.data.get("stale_lock"))
            if result.ok:
                status = DeploymentRunStatus.ROLLED_BACK
            elif data and data.rollback_error:
                status = DeploymentRunStatus.ROLLBACK_FAILED
            else:
                status = DeploymentRunStatus.FAILED
            self.history.finish_run(run_id, status=status, message=result.message, rolled_back=result.ok or bool(data and data.rolled_back),
                                    rollback_error=data.rollback_error if data else None,
                                    health_ok=data.health_check.ok if data and data.health_check else None,
                                    artifact_path=(data.release_path or data.backup_path) if data else None,
                                    retention=job.history_retention)
            payload = self._result_payload(result, data, kind="rollback", job=job)
            payload.update({"stale_lock": stale, "artifact_id": artifact.id})
            bus.log(f"Rollback of {job.name}: {result.message}", "ok" if result.ok else "error", "deploy")
            bus.broadcast("deploy.result", payload)

        return tasks.run_task(RUN_KEY, work)
