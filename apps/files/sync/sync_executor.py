from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from core.result import OperationResult
from file_ops.base import FileItem, FileKind
from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from file_ops.safety import ensure_not_protected, is_path_traversal, safe_destination
from sync.diff_engine import SyncAction, SyncPlanEntry, SyncPreview, SyncTargetSide
from sync.sync_job import SyncJob, SyncMode
from transfers.transfer_job import TransferJob, TransferStatus


@dataclass(frozen=True, slots=True)
class SyncExecutionPolicy:
    destructive_confirmed: bool = False
    block_conflicts: bool = True


@dataclass(frozen=True, slots=True)
class SyncExecutionResult:
    queued_transfers: int = 0
    local_deletes: int = 0
    remote_deletes: int = 0
    skipped: int = 0
    conflicts: int = 0


class SyncExecutor:
    async def execute(
        self,
        job: SyncJob,
        preview: SyncPreview,
        remote_ops,
        transfer_manager,
        *,
        policy: SyncExecutionPolicy | None = None,
    ) -> OperationResult:
        active_policy = policy or SyncExecutionPolicy()
        if preview.conflicts and active_policy.block_conflicts:
            return OperationResult.failure(
                "Sync execution blocked because conflicts exist.",
                warnings=preview.conflicts,
                suggested_fix="Resolve conflicts or change the sync mode before executing.",
                logs=[f"Blocked {len(preview.conflicts)} conflicting sync item(s)."],
            )
        if self._needs_destructive_confirmation(preview) and not active_policy.destructive_confirmed:
            return OperationResult.failure(
                "Sync execution requires confirmation for overwrites or deletes.",
                suggested_fix="Confirm the destructive sync summary before executing.",
            )

        local_root, remote_root = self._roots(job)
        transfer_jobs: list[TransferJob] = []
        local_deletes: list[Path] = []
        remote_deletes: list[str] = []
        skipped = 0

        keep_both_entries = [entry for entry in preview.entries if entry.action == SyncAction.KEEP_BOTH]
        for entry in keep_both_entries:
            keep_both_jobs = await self._execute_keep_both(
                entry,
                local_root,
                remote_root,
                remote_ops,
                transfer_manager,
            )
            transfer_jobs.extend(keep_both_jobs)
            incomplete = [transfer for transfer in keep_both_jobs if transfer.status != TransferStatus.COMPLETED]
            if incomplete:
                return OperationResult.failure(
                    "Could not preserve both conflict versions.",
                    technical_details=incomplete[0].error_message,
                    retryable=True,
                )

        for entry in preview.entries:
            if entry.action in {SyncAction.SKIP, SyncAction.CONFLICT, SyncAction.KEEP_BOTH}:
                skipped += 1 if entry.action == SyncAction.SKIP else 0
                continue
            if entry.action in {SyncAction.UPLOAD, SyncAction.OVERWRITE}:
                if entry.source_side == SyncTargetSide.LOCAL and entry.target_side == SyncTargetSide.REMOTE:
                    transfer_jobs.append(
                        transfer_manager.enqueue_upload_file(
                            remote_ops,
                            local_path=self._local_target(local_root, entry.path),
                            remote_path=self._remote_target(remote_root, entry.path),
                            conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
                        )
                    )
                    continue
            if entry.action == SyncAction.DOWNLOAD:
                if entry.source_side == SyncTargetSide.REMOTE and entry.target_side == SyncTargetSide.LOCAL:
                    transfer_jobs.append(
                        transfer_manager.enqueue_download_file(
                            remote_ops,
                            remote_item=self._remote_item(remote_root, entry),
                            local_path=self._local_target(local_root, entry.path),
                            conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
                        )
                    )
                    continue
            if entry.action == SyncAction.DELETE:
                if entry.target_side == SyncTargetSide.LOCAL:
                    local_deletes.append(self._local_target(local_root, entry.path))
                elif entry.target_side == SyncTargetSide.REMOTE:
                    remote_deletes.append(self._remote_target(remote_root, entry.path))

        if transfer_jobs:
            await transfer_manager.run_until_idle()
            incomplete = [transfer for transfer in transfer_jobs if transfer.status != TransferStatus.COMPLETED]
            if incomplete:
                return OperationResult.failure(
                    "Sync transfers did not all complete; deletes were not applied.",
                    technical_details=incomplete[0].error_message,
                    retryable=True,
                    logs=[f"Queued {len(transfer_jobs)} transfer(s) before failure."],
                )

        deleted_local = await self._delete_local_files(local_deletes)
        deleted_remote = await self._delete_remote_files(remote_ops, remote_deletes)
        result_data = SyncExecutionResult(
            queued_transfers=len(transfer_jobs),
            local_deletes=deleted_local,
            remote_deletes=deleted_remote,
            skipped=skipped,
            conflicts=len(preview.conflicts),
        )
        return OperationResult.success(
            "Sync execution completed.",
            data=result_data,
            logs=[
                f"Queued {len(transfer_jobs)} transfer(s).",
                f"Deleted {deleted_local} local file(s).",
                f"Deleted {deleted_remote} remote file(s).",
            ],
        )

    async def _execute_keep_both(
        self,
        entry: SyncPlanEntry,
        local_root: Path,
        remote_root: str,
        remote_ops,
        transfer_manager,
    ) -> list[TransferJob]:
        if not entry.alternate_path:
            raise ValueError(f"Keep-both conflict has no alternate path: {entry.path}")
        local_original = self._local_target(local_root, entry.path)
        local_alternate = self._local_target(local_root, entry.alternate_path)
        remote_original = self._remote_target(remote_root, entry.path)
        remote_alternate = self._remote_target(remote_root, entry.alternate_path)
        download = transfer_manager.enqueue_download_file(
            remote_ops,
            remote_item=FileItem(
                name=posixpath.basename(entry.path),
                path=remote_original,
                kind=FileKind.FILE,
                size=entry.destination_size,
            ),
            local_path=local_alternate,
            conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
        )
        await transfer_manager.run_until_idle()
        if download.status != TransferStatus.COMPLETED:
            return [download]
        preserve_remote = transfer_manager.enqueue_upload_file(
            remote_ops,
            local_path=local_alternate,
            remote_path=remote_alternate,
            conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
        )
        canonical = transfer_manager.enqueue_upload_file(
            remote_ops,
            local_path=local_original,
            remote_path=remote_original,
            conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
        )
        await transfer_manager.run_until_idle()
        return [download, preserve_remote, canonical]

    def _needs_destructive_confirmation(self, preview: SyncPreview) -> bool:
        if preview.deletes or preview.overwrites:
            return True
        return any(entry.action == SyncAction.DOWNLOAD and entry.destination_size is not None for entry in preview.entries)

    def _roots(self, job: SyncJob) -> tuple[Path, str]:
        if job.mode == SyncMode.REMOTE_TO_LOCAL:
            return Path(job.destination_path).expanduser(), job.source_path
        return Path(job.source_path).expanduser(), job.destination_path

    def _local_target(self, local_root: Path, relative_path: str) -> Path:
        return safe_destination(local_root, relative_path)

    def _remote_target(self, remote_root: str, relative_path: str) -> str:
        if is_path_traversal(relative_path):
            raise ValueError(f"Unsafe remote sync path: {relative_path}")
        if remote_root in {"", "."}:
            return posixpath.normpath(relative_path)
        return posixpath.normpath(posixpath.join(remote_root, relative_path))

    def _remote_item(self, remote_root: str, entry: SyncPlanEntry) -> FileItem:
        return FileItem(
            name=posixpath.basename(entry.path),
            path=self._remote_target(remote_root, entry.path),
            kind=FileKind.FILE,
            size=entry.source_size or entry.destination_size,
        )

    async def _delete_local_files(self, paths: list[Path]) -> int:
        deleted = 0
        for path in paths:
            if not path.exists():
                continue
            if not path.is_file():
                raise ValueError(f"Refusing to delete non-file local sync path: {path}")
            path.unlink()
            deleted += 1
        return deleted

    async def _delete_remote_files(self, remote_ops, paths: list[str]) -> int:
        deleted = 0
        for path in paths:
            ensure_not_protected(path)
            result = await remote_ops.delete(path, recursive=False)
            if not result.ok:
                raise RuntimeError(result.message)
            deleted += 1
        return deleted
