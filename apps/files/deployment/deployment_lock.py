from __future__ import annotations

import json
import posixpath
import socket
import threading
import time
from dataclasses import dataclass

from core.connections.ssh_async import sh_quote
from core.result import OperationResult, OperationStatus
from file_ops.safety import normalize_remote_path

from deployment.deployment_job import DeploymentJob


REMOTE_LOCK_EXIT_STATUS = 73


@dataclass(frozen=True, slots=True)
class DeploymentLock:
    key: str
    remote_path: str
    run_id: str


class DeploymentLockManager:
    _local_guard = threading.Lock()
    _local_locks: set[str] = set()

    def lock_key(self, job: DeploymentJob) -> str:
        return f"{job.profile_id or 'unknown'}:{normalize_remote_path(job.remote_target_folder)}"

    def remote_lock_path(self, job: DeploymentJob) -> str:
        target = normalize_remote_path(job.remote_target_folder)
        parent = posixpath.dirname(target.rstrip("/")) or "/"
        return posixpath.join(parent, ".rfm-locks", job.id)

    async def acquire(
        self,
        connection,
        job: DeploymentJob,
        run_id: str,
        *,
        break_stale: bool = False,
    ) -> OperationResult:
        key = self.lock_key(job)
        with self._local_guard:
            if key in self._local_locks:
                return OperationResult.failure("Another deployment to this server target is already running.")
            self._local_locks.add(key)

        remote_path = self.remote_lock_path(job)
        metadata = {
            "run_id": run_id,
            "created_at": int(time.time()),
            "host": socket.gethostname(),
            "app": "remote-file-manager",
        }
        try:
            if break_stale:
                removal = await self._run(connection, f"rm -rf -- {sh_quote(remote_path)}")
                if not removal.ok:
                    self._release_local(key)
                    return OperationResult.failure(
                        "Could not remove the confirmed stale deployment lock.",
                        technical_details=removal.technical_details,
                    )
            parent = posixpath.dirname(remote_path)
            payload = json.dumps(metadata, separators=(",", ":"))
            command = (
                f"mkdir -p {sh_quote(parent)} && "
                f"if mkdir {sh_quote(remote_path)} 2>/dev/null; then "
                f"printf '%s' {sh_quote(payload)} > {sh_quote(posixpath.join(remote_path, 'owner.json'))}; "
                "exit 0; "
                f"else cat {sh_quote(posixpath.join(remote_path, 'owner.json'))} 2>/dev/null || true; "
                f"exit {REMOTE_LOCK_EXIT_STATUS}; fi"
            )
            result = await connection.run_command(command)
            data = result.data if isinstance(result.data, dict) else {}
            status = int(data.get("exit_status", 1))
            if result.ok and status == 0:
                return OperationResult.success(
                    "Deployment lock acquired.",
                    data=DeploymentLock(key, remote_path, run_id),
                )
            owner = self._parse_owner(str(data.get("stdout") or ""))
            created_at = self._owner_created_at(owner)
            stale = bool(
                created_at is not None
                and int(time.time()) - created_at
                >= max(1, int(job.stale_lock_seconds))
            )
            return OperationResult(
                status=OperationStatus.FAILED,
                message="The remote deployment target is locked.",
                technical_details=str(data.get("stderr") or "") or None,
                retryable=stale,
                suggested_fix=(
                    "The lock is stale. Confirm removal and retry the deployment."
                    if stale
                    else "Wait for the active deployment to finish."
                ),
                data={"stale_lock": stale, "owner": owner, "remote_path": remote_path},
            )
        except Exception:
            self._release_local(key)
            raise
        finally:
            if "result" in locals() and not (result.ok and int((result.data or {}).get("exit_status", 1)) == 0):
                self._release_local(key)

    async def release(self, connection, lock: DeploymentLock | None) -> OperationResult:  # type: ignore[no-untyped-def]
        if lock is None:
            return OperationResult.skipped("No deployment lock was held.")
        try:
            result = await self._run(connection, f"rm -rf -- {sh_quote(lock.remote_path)}")
            return result
        finally:
            self._release_local(lock.key)

    async def _run(self, connection, command: str) -> OperationResult:  # type: ignore[no-untyped-def]
        result = await connection.run_command(command)
        data = result.data if isinstance(result.data, dict) else {}
        if result.ok and int(data.get("exit_status", 1)) == 0:
            return OperationResult.success("Deployment lock operation completed.")
        return OperationResult.failure(
            "Deployment lock operation failed.",
            technical_details=str(data.get("stderr") or result.technical_details or "") or None,
        )

    def _release_local(self, key: str) -> None:
        with self._local_guard:
            self._local_locks.discard(key)

    def _parse_owner(self, text: str) -> dict:
        try:
            value = json.loads(text.strip())
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _owner_created_at(self, owner: dict) -> int | None:
        try:
            return int(owner["created_at"])
        except (KeyError, TypeError, ValueError):
            return None
