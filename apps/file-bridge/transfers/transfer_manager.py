from __future__ import annotations

import asyncio
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.events import Event
from core.result import OperationResult
from file_ops.base import FileItem
from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from file_ops.safety import safe_destination
from transfers.conflict_resolver import ConflictResolver
from transfers.events import TransferLogEvent, TransferProgressEvent
from transfers.progress import ProgressThrottler
from transfers.queue import TransferQueue
from transfers.transfer_job import TransferDirection, TransferJob, TransferStatus

MIN_CONCURRENT_TRANSFERS = 1
DEFAULT_CONCURRENT_TRANSFERS = 3
MAX_CONCURRENT_TRANSFERS = 16
DEFAULT_PROGRESS_EMIT_INTERVAL_SECONDS = 0.08


@dataclass(slots=True)
class TransferPlan:
    kind: str
    remote_ops: object
    local_path: Path
    remote_path: str
    conflict_decision: ConflictDecision


class TransferManager:
    """Queues and runs transfers on the asyncio runtime. Qt-free: listeners subscribe to plain events, which fire
    on the runtime thread (the Qt UI re-emits them through ``ui.qt_bridge.QtTransferSignals``)."""

    def __init__(
        self,
        *,
        max_concurrent: int = DEFAULT_CONCURRENT_TRANSFERS,
        progress_emit_interval: float = DEFAULT_PROGRESS_EMIT_INTERVAL_SECONDS,
    ) -> None:
        self.job_updated: Event[TransferJob] = Event("transfer.job_updated")
        self.log_event: Event[TransferLogEvent] = Event("transfer.log_event")
        self.batch_finished: Event[str] = Event("transfer.batch_finished")
        self.queue = TransferQueue()
        self.max_concurrent = clamp_concurrent_transfers(max_concurrent)
        self.progress_emit_interval = max(0.01, float(progress_emit_interval))
        self._plans: dict[str, TransferPlan] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._progress_throttlers: dict[str, ProgressThrottler] = {}
        self._progress_seen: set[str] = set()
        self._progress_final_emitted: set[str] = set()
        self._external_tasks: dict[str, asyncio.Task] = {}

    def set_max_concurrent(self, value: int) -> None:
        self.max_concurrent = clamp_concurrent_transfers(value)

    def enqueue(self, job: TransferJob) -> TransferJob:
        self.queue.add(job)
        self.job_updated.emit(job)
        self._log(job, "info", f"Transfer queued: {job.source_path} -> {job.destination_path}")
        return job

    def add_external_job(self, job: TransferJob) -> TransferJob:
        job.mark_running()
        self.queue.add(job)
        self.job_updated.emit(job)
        self._log(job, "info", "Cross-server transfer started.")
        return job

    def register_external_task(self, job: TransferJob, task: asyncio.Task | None) -> None:
        if task is not None:
            self._external_tasks[job.id] = task

    def notify_external_job(self, job: TransferJob) -> None:
        self.job_updated.emit(job)

    def finish_external_job(self, job: TransferJob) -> None:
        self._external_tasks.pop(job.id, None)
        self.job_updated.emit(job)
        level = "info" if job.status == TransferStatus.COMPLETED else "warning" if job.status == TransferStatus.CANCELLED else "error"
        self._log(job, level, f"Cross-server transfer {job.status.value}.", job.error_message)

    def enqueue_upload_file(
        self,
        remote_ops: object,
        *,
        local_path: str | Path,
        remote_path: str,
        batch_id: str | None = None,
        conflict_decision: ConflictDecision | None = None,
    ) -> TransferJob:
        source = Path(local_path)
        job = TransferJob(
            source_connection=None,
            destination_connection=None,
            source_path=str(source),
            destination_path=remote_path,
            direction=TransferDirection.LOCAL_TO_SERVER,
            size=source.stat().st_size if source.exists() and source.is_file() else None,
            batch_id=batch_id or str(uuid4()),
            conflict_policy=(conflict_decision or default_conflict_decision()).policy,
        )
        self._plans[job.id] = TransferPlan(
            kind="upload_file",
            remote_ops=remote_ops,
            local_path=source,
            remote_path=remote_path,
            conflict_decision=conflict_decision or default_conflict_decision(),
        )
        return self.enqueue(job)

    def enqueue_upload_folder(
        self,
        remote_ops: object,
        *,
        local_folder: str | Path,
        remote_folder: str,
        batch_id: str | None = None,
        conflict_decision: ConflictDecision | None = None,
    ) -> list[TransferJob]:
        active_batch_id = batch_id or str(uuid4())
        root = Path(local_folder)
        jobs: list[TransferJob] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            jobs.append(
                self.enqueue_upload_file(
                    remote_ops,
                    local_path=path,
                    remote_path=posixpath.join(remote_folder, relative),
                    batch_id=active_batch_id,
                    conflict_decision=conflict_decision,
                )
            )
        return jobs

    def enqueue_download_file(
        self,
        remote_ops: object,
        *,
        remote_item: FileItem,
        local_path: str | Path,
        batch_id: str | None = None,
        conflict_decision: ConflictDecision | None = None,
    ) -> TransferJob:
        target = Path(local_path)
        job = TransferJob(
            source_connection=None,
            destination_connection=None,
            source_path=remote_item.path,
            destination_path=str(target),
            direction=TransferDirection.SERVER_TO_LOCAL,
            size=remote_item.size,
            batch_id=batch_id or str(uuid4()),
            conflict_policy=(conflict_decision or default_conflict_decision()).policy,
        )
        self._plans[job.id] = TransferPlan(
            kind="download_file",
            remote_ops=remote_ops,
            local_path=target,
            remote_path=remote_item.path,
            conflict_decision=conflict_decision or default_conflict_decision(),
        )
        return self.enqueue(job)

    async def enqueue_download_folder(
        self,
        remote_ops: object,
        *,
        remote_item: FileItem,
        local_folder: str | Path,
        conflict_decision: ConflictDecision | None = None,
    ) -> list[TransferJob]:
        batch_id = str(uuid4())
        target_root = Path(local_folder)
        files = await self._remote_tree_files(remote_ops, remote_item.path)
        # Every local target is checked before anything is queued: one hostile name stops the whole batch
        # instead of leaving it half-downloaded.
        targets = [(item, safe_destination(target_root, posixpath.relpath(item.path, remote_item.path))) for item in files]
        return [
            self.enqueue_download_file(
                remote_ops,
                remote_item=item,
                local_path=target,
                batch_id=batch_id,
                conflict_decision=conflict_decision,
            )
            for item, target in targets
        ]

    async def run_until_idle(self) -> OperationResult:
        if self._scheduler_task and not self._scheduler_task.done():
            await self._scheduler_task
            return OperationResult.success("Transfer queue is idle.")
        self._scheduler_task = asyncio.create_task(self._run_scheduler())
        await self._scheduler_task
        return OperationResult.success("Transfer queue is idle.")

    async def cancel_job(self, job_id: str) -> OperationResult:
        job = self.queue.get(job_id)
        if job is None:
            return OperationResult.failure("Transfer job was not found.")
        if job.status == TransferStatus.QUEUED:
            job.mark_cancelled()
            await self._cleanup_cancelled_partial(job)
            self.job_updated.emit(job)
            self._log(job, "warning", "Queued transfer cancelled.")
            return OperationResult.success("Transfer cancelled.", data=job)
        task = self._tasks.get(job_id)
        if task is None:
            task = self._external_tasks.get(job_id)
        if task is not None:
            job.cancel_requested = True
            task.cancel()
            self._log(job, "warning", "Cancellation requested.")
            return OperationResult.success("Transfer cancellation requested.", data=job)
        return OperationResult.skipped("Transfer is not queued or running.", warnings=[job_id])

    async def cancel_batch(self, batch_id: str) -> OperationResult:
        jobs = [job for job in self.queue.jobs if job.batch_id == batch_id]
        if not jobs:
            return OperationResult.skipped("No transfer jobs were found for this batch.")
        results = []
        for job in jobs:
            if job.status not in {TransferStatus.QUEUED, TransferStatus.RUNNING}:
                continue
            results.append(await self.cancel_job(job.id))
        return OperationResult.success(
            f"Cancellation requested for {len(results)} transfer(s).",
            data=jobs,
        )

    async def retry_job(self, job_id: str) -> OperationResult:
        job = self.queue.retry_job(job_id)
        if job is None:
            return OperationResult.failure("Only failed or cancelled transfer jobs can be retried.")
        self._reset_progress_tracking(job.id)
        self.job_updated.emit(job)
        self._log(job, "info", f"Transfer retry queued (attempt {job.retry_count}).")
        await self.run_until_idle()
        return OperationResult.success("Transfer retried.", data=job)

    async def retry_failed(self) -> OperationResult:
        jobs = self.queue.retry_failed()
        for job in jobs:
            self._reset_progress_tracking(job.id)
            self.job_updated.emit(job)
            self._log(job, "info", f"Transfer retry queued (attempt {job.retry_count}).")
        await self.run_until_idle()
        return OperationResult.success(f"{len(jobs)} failed transfer(s) queued for retry.", data=jobs)

    def clear_completed(self) -> None:
        self.queue.clear_completed()

    def clear_failed(self) -> None:
        self.queue.clear_failed()

    async def upload_file(
        self,
        remote_ops: object,
        *,
        local_path: str | Path,
        remote_path: str,
        on_progress: Callable[[TransferJob, TransferProgressEvent], None] | None = None,
    ) -> OperationResult:
        source = Path(local_path)
        job = TransferJob(
            source_connection=None,
            destination_connection=None,
            source_path=str(source),
            destination_path=remote_path,
            direction=TransferDirection.LOCAL_TO_SERVER,
            size=source.stat().st_size if source.exists() and source.is_file() else None,
        )
        job.mark_running()
        result = await remote_ops.upload_file(
            source,
            remote_path,
            progress_callback=self._progress_callback(job, on_progress),
        )
        if result.ok:
            job.mark_completed()
        else:
            job.mark_failed(result.message)
        result.data = job
        return result

    async def download_file(
        self,
        remote_ops: object,
        *,
        remote_item: FileItem,
        local_path: str | Path,
        on_progress: Callable[[TransferJob, TransferProgressEvent], None] | None = None,
    ) -> OperationResult:
        job = TransferJob(
            source_connection=None,
            destination_connection=None,
            source_path=remote_item.path,
            destination_path=str(local_path),
            direction=TransferDirection.SERVER_TO_LOCAL,
            size=remote_item.size,
        )
        job.mark_running()
        result = await remote_ops.download_file(
            remote_item.path,
            local_path,
            progress_callback=self._progress_callback(job, on_progress),
        )
        if result.ok:
            job.mark_completed()
        else:
            job.mark_failed(result.message)
        result.data = job
        return result

    async def record_direct_transfer(
        self,
        *,
        source_path: str,
        destination_path: str,
        direction: TransferDirection,
    ) -> OperationResult:
        job = TransferJob(
            source_connection=None,
            destination_connection=None,
            source_path=source_path,
            destination_path=destination_path,
            direction=direction,
        )
        job.mark_completed()
        self.enqueue(job)
        return OperationResult.success("Transfer recorded.", data=job)

    async def _run_scheduler(self) -> None:
        touched_batches: set[str] = set()
        while True:
            while len(self._tasks) < self.max_concurrent:
                job = next((item for item in self.queue.jobs if item.status == TransferStatus.QUEUED), None)
                if job is None:
                    break
                touched_batches.add(job.batch_id or job.id)
                job.mark_running()
                self.job_updated.emit(job)
                self._log(job, "info", "Transfer started.")
                task = asyncio.create_task(self._run_job(job))
                self._tasks[job.id] = task
            if not self._tasks:
                break
            done, _pending = await asyncio.wait(self._tasks.values(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                job_id = next((candidate for candidate, candidate_task in self._tasks.items() if candidate_task == task), None)
                if job_id:
                    self._tasks.pop(job_id, None)
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        for batch_id in touched_batches:
            self.batch_finished.emit(batch_id)

    async def _run_job(self, job: TransferJob) -> None:
        plan = self._plans[job.id]
        try:
            if plan.kind == "upload_file":
                result = await self._upload_file_plan(job, plan)
            elif plan.kind == "download_file":
                result = await self._download_file_plan(job, plan)
            else:
                result = OperationResult.failure(f"Unknown transfer plan: {plan.kind}")
            if result.ok and job.status != TransferStatus.CANCELLED:
                job.mark_completed()
                self._log(job, "info", result.message)
            elif job.status != TransferStatus.CANCELLED:
                job.mark_failed(result.message)
                self._log(job, "error", result.message, result.technical_details)
        except asyncio.CancelledError:
            job.mark_cancelled()
            await self._cleanup_cancelled_partial(job)
            self._log(job, "warning", "Transfer cancelled.")
        except Exception as exc:  # pragma: no cover - defensive
            job.mark_failed(f"Transfer failed: {exc}")
            self._log(job, "error", "Transfer failed.", f"{type(exc).__name__}: {exc}")
        finally:
            self.job_updated.emit(job)
            self._reset_progress_tracking(job.id)

    async def _upload_file_plan(self, job: TransferJob, plan: TransferPlan) -> OperationResult:
        remote_path = await self._destination_after_remote_conflict(plan.remote_ops, plan.remote_path, plan.conflict_decision)
        if remote_path is None:
            job.mark_cancelled("Transfer skipped by conflict policy.")
            return OperationResult.success("Transfer skipped by conflict policy.", data=job)
        temp_path = f"{remote_path}.part-{job.id}"
        job.temp_path = temp_path
        await self._ensure_remote_parent(plan.remote_ops, remote_path)
        result = await plan.remote_ops.upload_file(
            plan.local_path,
            temp_path,
            progress_callback=self._progress_callback(job, None),
        )
        if not result.ok:
            return OperationResult.failure(
                f"{result.message} Partial upload left at {temp_path}.",
                technical_details=result.technical_details,
                retryable=result.retryable,
            )
        if remote_path != plan.remote_path:
            job.destination_path = remote_path
        if plan.conflict_decision.policy == ConflictPolicy.OVERWRITE:
            await plan.remote_ops.delete(remote_path, recursive=False)
        rename_result = await plan.remote_ops.rename(temp_path, remote_path)
        if rename_result.ok:
            job.temp_path = None
        return rename_result

    async def _download_file_plan(self, job: TransferJob, plan: TransferPlan) -> OperationResult:
        local_path = self._destination_after_local_conflict(plan.local_path, plan.conflict_decision)
        if local_path is None:
            job.mark_cancelled("Transfer skipped by conflict policy.")
            return OperationResult.success("Transfer skipped by conflict policy.", data=job)
        temp_path = local_path.with_name(f"{local_path.name}.part-{job.id}")
        job.temp_path = str(temp_path)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        result = await plan.remote_ops.download_file(
            plan.remote_path,
            temp_path,
            progress_callback=self._progress_callback(job, None),
        )
        if not result.ok:
            return OperationResult.failure(
                f"{result.message} Partial download left at {temp_path}.",
                technical_details=result.technical_details,
                retryable=result.retryable,
            )
        if local_path != plan.local_path:
            job.destination_path = str(local_path)
        if local_path.exists() and plan.conflict_decision.policy == ConflictPolicy.OVERWRITE:
            local_path.unlink()
        temp_path.replace(local_path)
        job.temp_path = None
        return OperationResult.success("File downloaded.", affected_paths=[plan.remote_path, str(local_path)])

    async def _destination_after_remote_conflict(
        self,
        remote_ops: object,
        remote_path: str,
        decision: ConflictDecision,
    ) -> str | None:
        exists = await self._remote_exists(remote_ops, remote_path)
        if not exists:
            return remote_path
        if decision.policy == ConflictPolicy.SKIP:
            return None
        if decision.policy == ConflictPolicy.RENAME:
            return decision.alternate_name or ConflictResolver(ConflictPolicy.RENAME).resolve(
                source_path="",
                destination_path=remote_path,
            ).alternate_name
        if decision.policy == ConflictPolicy.OVERWRITE:
            return remote_path
        raise RuntimeError("Transfer conflict requires overwrite, skip, or rename decision.")

    def _destination_after_local_conflict(self, local_path: Path, decision: ConflictDecision) -> Path | None:
        if not local_path.exists():
            return local_path
        if decision.policy == ConflictPolicy.SKIP:
            return None
        if decision.policy == ConflictPolicy.RENAME:
            alternate = decision.alternate_name or ConflictResolver(ConflictPolicy.RENAME).resolve(
                source_path="",
                destination_path=str(local_path),
            ).alternate_name
            return Path(alternate) if alternate else local_path
        if decision.policy == ConflictPolicy.OVERWRITE:
            return local_path
        raise RuntimeError("Transfer conflict requires overwrite, skip, or rename decision.")

    async def _remote_exists(self, remote_ops: object, remote_path: str) -> bool:
        stat = getattr(remote_ops, "stat", None)
        if stat is None:
            return False
        result = await stat(remote_path)
        return bool(result.ok)

    async def _ensure_remote_parent(self, remote_ops: object, remote_path: str) -> None:
        parent = posixpath.dirname(remote_path)
        if not parent or parent == ".":
            return
        ensure_folder = getattr(remote_ops, "ensure_folder", None)
        if ensure_folder is not None:
            await ensure_folder(parent)

    async def _remote_tree_files(self, remote_ops: object, remote_path: str) -> list[FileItem]:
        listed = await remote_ops.list_dir(remote_path, show_hidden=True)
        if not listed.ok:
            raise RuntimeError(listed.message)
        files: list[FileItem] = []
        for item in listed.data or []:
            if item.is_dir:
                files.extend(await self._remote_tree_files(remote_ops, item.path))
            elif item.is_file:
                files.append(item)
        return files

    async def _cleanup_cancelled_partial(self, job: TransferJob) -> None:
        if not job.temp_path:
            return
        plan = self._plans.get(job.id)
        try:
            if job.direction == TransferDirection.LOCAL_TO_SERVER and plan is not None:
                await plan.remote_ops.delete(job.temp_path, recursive=False)
            else:
                Path(job.temp_path).unlink(missing_ok=True)
        except Exception:
            pass

    def _progress_callback(
        self,
        job: TransferJob,
        on_progress: Callable[[TransferJob, TransferProgressEvent], None] | None,
    ) -> Callable[[str, str, int, int], None]:
        def callback(source_path: str, destination_path: str, bytes_done: int, bytes_total: int) -> None:
            first_progress = job.id not in self._progress_seen
            final_progress = bytes_total > 0 and bytes_done >= bytes_total
            final_already_emitted = job.id in self._progress_final_emitted
            job.update_progress(
                bytes_done=bytes_done,
                bytes_total=bytes_total,
                current_file=source_path or destination_path,
            )
            event = TransferProgressEvent(
                job_id=job.id,
                source_path=source_path,
                destination_path=destination_path,
                bytes_done=bytes_done,
                bytes_total=bytes_total,
                current_file=job.current_file,
            )
            if first_progress:
                self._progress_seen.add(job.id)
                self._log(job, "info", "First transfer progress received.")
            if final_progress and not final_already_emitted:
                self._progress_final_emitted.add(job.id)
                self._log(job, "info", "Final transfer progress reached 100%.")
            if final_already_emitted:
                return

            throttler = self._progress_throttlers.setdefault(
                job.id,
                ProgressThrottler(interval_seconds=self.progress_emit_interval),
            )
            should_emit = throttler.should_emit(force=first_progress or final_progress)
            if not should_emit:
                return

            self.job_updated.emit(job)
            if on_progress is not None:
                on_progress(job, event)

        return callback

    def _reset_progress_tracking(self, job_id: str) -> None:
        self._progress_throttlers.pop(job_id, None)
        self._progress_seen.discard(job_id)
        self._progress_final_emitted.discard(job_id)

    def _log(
        self,
        job: TransferJob,
        level: str,
        message: str,
        technical_details: str | None = None,
    ) -> None:
        job.logs.append(message)
        self.log_event.emit(
            TransferLogEvent(
                job_id=job.id,
                level=level,
                message=message,
                technical_details=technical_details,
            )
        )


def default_conflict_decision() -> ConflictDecision:
    return ConflictDecision(ConflictPolicy.ASK_EVERY_TIME)


def clamp_concurrent_transfers(value: int) -> int:
    return max(MIN_CONCURRENT_TRANSFERS, min(MAX_CONCURRENT_TRANSFERS, int(value)))
