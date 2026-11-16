from __future__ import annotations

import asyncio
import posixpath
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from core.connections.rsync_adapter import RsyncAdapter, RsyncDirection
from core.result import OperationResult
from file_ops.base import FileItem, FileKind
from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from file_ops.safety import ensure_not_protected, is_path_traversal
from transfers.transfer_job import TransferDirection, TransferJob, TransferStatus


class RemoteTransferMode(StrEnum):
    AUTO = "auto"
    LOCAL_RELAY = "local_relay"
    RSYNC_PUSH = "rsync_push"
    RSYNC_PULL = "rsync_pull"


@dataclass(frozen=True, slots=True)
class RemoteEndpoint:
    profile_id: str
    name: str
    connection: object
    operations: object


@dataclass(frozen=True, slots=True)
class RemoteTransferFile:
    source_path: str
    relative_path: str
    size: int | None = None


@dataclass(slots=True)
class RemoteToRemotePlan:
    source: RemoteEndpoint
    destination: RemoteEndpoint
    destination_root: str
    source_root: str
    files: list[RemoteTransferFile]
    conflicts: list[str] = field(default_factory=list)
    mode: RemoteTransferMode = RemoteTransferMode.AUTO
    batch_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def total_bytes(self) -> int:
        return sum(item.size or 0 for item in self.files)


class RemoteTransferService:
    def __init__(self, transfer_manager, *, rsync_adapter: RsyncAdapter | None = None) -> None:  # type: ignore[no-untyped-def]
        self.transfer_manager = transfer_manager
        self.rsync = rsync_adapter or RsyncAdapter()

    async def preview(
        self,
        source: RemoteEndpoint,
        destination: RemoteEndpoint,
        item: FileItem,
        destination_root: str,
        *,
        mode: RemoteTransferMode = RemoteTransferMode.AUTO,
    ) -> OperationResult:
        try:
            ensure_not_protected(destination_root)
            files: list[RemoteTransferFile] = []
            if item.is_dir:
                await self._collect(source.operations, item.path, item.path, files)
            else:
                files.append(RemoteTransferFile(item.path, item.name, item.size))
            conflicts: list[str] = []
            for transfer_file in files:
                target = posixpath.join(destination_root, transfer_file.relative_path)
                existing = await destination.operations.stat(target)
                if existing.ok:
                    conflicts.append(target)
            plan = RemoteToRemotePlan(
                source=source,
                destination=destination,
                destination_root=destination_root,
                source_root=item.path,
                files=files,
                conflicts=conflicts,
                mode=mode,
            )
            return OperationResult.success(
                f"Cross-server preview contains {len(files)} file(s).",
                data=plan,
                logs=[f"Estimated transfer size: {plan.total_bytes} bytes."],
            )
        except Exception as exc:
            return OperationResult.failure(
                "Could not build cross-server transfer preview.",
                technical_details=f"{type(exc).__name__}: {exc}",
            )

    async def execute(self, plan: RemoteToRemotePlan) -> OperationResult:
        selected_mode, explanation = await self._select_mode(plan)
        if (
            plan.mode in {RemoteTransferMode.RSYNC_PUSH, RemoteTransferMode.RSYNC_PULL}
            and selected_mode == RemoteTransferMode.LOCAL_RELAY
        ):
            return OperationResult.failure(
                "Requested direct rsync mode is unavailable.",
                technical_details=explanation,
                suggested_fix="Choose Auto or Secure local relay, or configure server-to-server SSH trust.",
            )
        if selected_mode in {RemoteTransferMode.RSYNC_PUSH, RemoteTransferMode.RSYNC_PULL}:
            result = await self._execute_rsync(plan, selected_mode)
            if result.ok or plan.mode != RemoteTransferMode.AUTO:
                result.logs.append(explanation)
                return result
            explanation = f"{explanation} Falling back to local relay because rsync could not start."
        result = await self._execute_local_relay(plan)
        result.logs.append(explanation)
        return result

    async def _select_mode(self, plan: RemoteToRemotePlan) -> tuple[RemoteTransferMode, str]:
        if plan.mode == RemoteTransferMode.LOCAL_RELAY:
            return plan.mode, "Local relay was selected explicitly."
        requested = plan.mode
        if not (
            getattr(plan.source.connection, "capabilities", None)
            and getattr(plan.destination.connection, "capabilities", None)
            and plan.source.connection.capabilities.can_exec_command
            and plan.destination.connection.capabilities.can_exec_command
        ):
            return RemoteTransferMode.LOCAL_RELAY, "Local relay is used because both endpoints do not provide SSH."
        source_probe = await self.rsync.probe_remote(plan.source.connection)
        destination_probe = await self.rsync.probe_remote(plan.destination.connection)
        if not source_probe.ok or not destination_probe.ok:
            return RemoteTransferMode.LOCAL_RELAY, "Local relay is used because rsync is unavailable on an endpoint."
        if requested == RemoteTransferMode.RSYNC_PULL:
            auth = await self.rsync.probe_server_auth(plan.destination.connection, plan.source.connection.profile)
            return (requested, "Destination-side rsync pull is available.") if auth.ok else (
                RemoteTransferMode.LOCAL_RELAY,
                auth.suggested_fix or auth.message,
            )
        auth = await self.rsync.probe_server_auth(plan.source.connection, plan.destination.connection.profile)
        if auth.ok:
            return RemoteTransferMode.RSYNC_PUSH, "Source-side rsync push is available."
        return RemoteTransferMode.LOCAL_RELAY, auth.suggested_fix or auth.message

    async def _execute_rsync(
        self,
        plan: RemoteToRemotePlan,
        mode: RemoteTransferMode,
    ) -> OperationResult:
        if mode == RemoteTransferMode.RSYNC_PUSH:
            command = self.rsync.build_remote_command(
                source_path=plan.source_root,
                destination_profile=plan.destination.connection.profile,
                destination_path=plan.destination_root,
                direction=RsyncDirection.REMOTE_PUSH,
            )
            result = await plan.source.connection.run_command(command)
        else:
            command = self.rsync.build_remote_command(
                source_path=plan.destination_root,
                destination_profile=plan.source.connection.profile,
                destination_path=plan.source_root,
                direction=RsyncDirection.REMOTE_PULL,
            )
            result = await plan.destination.connection.run_command(command)
        if not result.ok or result.data.get("exit_status") != 0:
            return OperationResult.failure(
                "Direct rsync transfer failed.",
                technical_details=(result.data or {}).get("stderr") if result.data else result.technical_details,
                retryable=True,
            )
        return OperationResult.success("Direct server-to-server rsync completed.")

    async def _execute_local_relay(self, plan: RemoteToRemotePlan) -> OperationResult:
        with tempfile.TemporaryDirectory(prefix="rfm-server-relay-") as folder:
            root = Path(folder)
            root.chmod(0o700)
            if plan.total_bytes and shutil.disk_usage(root).free < plan.total_bytes:
                return OperationResult.failure(
                    "Not enough local disk space for relay transfer.",
                    suggested_fix="Free local disk space or use direct rsync mode.",
                )
            jobs = [
                self._new_job(plan, item)
                for item in plan.files
            ]
            semaphore = asyncio.Semaphore(self.transfer_manager.max_concurrent)

            async def run(job: TransferJob, item: RemoteTransferFile) -> None:
                async with semaphore:
                    await self._relay_file(plan, item, root, job)

            tasks = [asyncio.create_task(run(job, item)) for job, item in zip(jobs, plan.files)]
            await asyncio.gather(*tasks, return_exceptions=True)
            failed = [job for job in jobs if job.status != TransferStatus.COMPLETED]
            if failed:
                result = OperationResult.failure(
                    f"{len(failed)} cross-server transfer(s) failed.",
                    technical_details=failed[0].error_message,
                    retryable=True,
                )
                result.data = jobs
                return result
            return OperationResult.success(
                f"Transferred {len(jobs)} file(s) through secure local relay.",
                data=jobs,
            )

    def _new_job(self, plan: RemoteToRemotePlan, item: RemoteTransferFile) -> TransferJob:
        destination = posixpath.join(plan.destination_root, item.relative_path)
        job = TransferJob(
            source_connection=plan.source.profile_id,
            destination_connection=plan.destination.profile_id,
            source_path=item.source_path,
            destination_path=destination,
            direction=TransferDirection.SERVER_TO_SERVER,
            size=item.size,
            bytes_total=item.size,
            batch_id=plan.batch_id,
        )
        self.transfer_manager.add_external_job(job)
        return job

    async def _relay_file(
        self,
        plan: RemoteToRemotePlan,
        item: RemoteTransferFile,
        root: Path,
        job: TransferJob,
    ) -> None:
        task = asyncio.current_task()
        self.transfer_manager.register_external_task(job, task)
        local_path = root / job.id / Path(item.relative_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        destination = posixpath.join(plan.destination_root, item.relative_path)
        temp_destination = f"{destination}.part-{job.id}"
        job.temp_path = temp_destination
        try:
            def download_progress(_source: str, _destination: str, done: int, total: int) -> None:
                self._update_external_progress(job, done, total, stage=0)

            download = await plan.source.operations.download_file(
                item.source_path,
                local_path,
                progress_callback=download_progress,
            )
            if not download.ok:
                raise RuntimeError(download.message)
            parent = posixpath.dirname(destination)
            if parent:
                ensured = await plan.destination.operations.ensure_folder(parent)
                if not ensured.ok:
                    raise RuntimeError(ensured.message)

            def upload_progress(_source: str, _destination: str, done: int, total: int) -> None:
                self._update_external_progress(job, done, total, stage=1)

            upload = await plan.destination.operations.upload_file(
                local_path,
                temp_destination,
                progress_callback=upload_progress,
            )
            if not upload.ok:
                raise RuntimeError(upload.message)
            existing = await plan.destination.operations.stat(destination)
            if existing.ok:
                await plan.destination.operations.delete(destination, recursive=False)
            renamed = await plan.destination.operations.rename(temp_destination, destination)
            if not renamed.ok:
                raise RuntimeError(renamed.message)
            job.temp_path = None
            job.mark_completed()
        except asyncio.CancelledError:
            job.mark_cancelled()
            try:
                await plan.destination.operations.delete(temp_destination, recursive=False)
            except Exception:
                pass
            raise
        except Exception as exc:
            job.mark_failed(f"{exc} Partial destination may remain at {temp_destination}.")
        finally:
            self.transfer_manager.finish_external_job(job)

    def _update_external_progress(self, job: TransferJob, done: int, total: int, *, stage: int) -> None:
        effective_total = max(total, job.bytes_total or total, 1)
        combined_done = int((stage * effective_total) + done)
        job.update_progress(bytes_done=combined_done, bytes_total=effective_total * 2, current_file=job.source_path)
        self.transfer_manager.notify_external_job(job)

    async def _collect(
        self,
        operations,
        root: str,
        current: str,
        files: list[RemoteTransferFile],
    ) -> None:  # type: ignore[no-untyped-def]
        result = await operations.list_dir(current, show_hidden=True)
        if not result.ok:
            raise RuntimeError(result.message)
        for item in result.data:
            if item.is_dir:
                await self._collect(operations, root, item.path, files)
            elif item.kind == FileKind.FILE:
                relative_path = posixpath.relpath(item.path, root)
                if is_path_traversal(relative_path):
                    raise ValueError(f"Unsafe source path returned by remote adapter: {item.path}")
                files.append(
                    RemoteTransferFile(
                        source_path=item.path,
                        relative_path=relative_path,
                        size=item.size,
                    )
                )
