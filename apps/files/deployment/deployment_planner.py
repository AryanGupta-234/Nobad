from __future__ import annotations

import asyncio
import os
import posixpath
import re
from datetime import UTC, datetime
from pathlib import Path

from core.result import OperationResult
from file_ops.base import FileItem
from file_ops.safety import ensure_not_protected, normalize_remote_path
from sync.diff_engine import SyncAction, SyncManifestEntry, SyncPlanEntry, SyncPreview
from sync.ignore_rules import should_ignore
from sync.sync_job import SyncJob, SyncMode
from sync.sync_planner import SyncPlanner

from deployment.deployment_job import DeploymentJob, DeploymentMode, DeploymentPreview


class DeploymentPlanner:
    def __init__(self) -> None:
        self._sync_planner = SyncPlanner()

    async def build_preview(self, job: DeploymentJob, remote_ops) -> OperationResult:  # type: ignore[no-untyped-def]
        validation = self.validate(job)
        if not validation.ok:
            return validation

        local_root = Path(job.local_build_folder).expanduser().resolve()
        remote_root = normalize_remote_path(job.remote_target_folder)
        local_manifest = await self._local_manifest(local_root, job.ignore_patterns)

        target_stat = await remote_ops.stat(remote_root)
        target_exists = bool(target_stat.ok)
        remote_manifest: list[SyncManifestEntry] = []
        if target_exists:
            item: FileItem = target_stat.data
            if not item.is_dir:
                return OperationResult.failure("Remote deployment target exists but is not a folder.")
            remote_result = await self._remote_manifest(remote_ops, remote_root, job.ignore_patterns)
            if not remote_result.ok:
                return remote_result
            remote_manifest = remote_result.data
        elif not self._is_missing_result(target_stat):
            return OperationResult.failure(
                "Could not inspect the remote deployment target.",
                technical_details=target_stat.technical_details or target_stat.message,
                retryable=True,
            )

        sync_job = SyncJob(
            name=job.name,
            mode=SyncMode.LOCAL_TO_REMOTE,
            source_path=str(local_root),
            destination_path=remote_root,
            ignore_patterns=job.ignore_patterns,
        )
        sync_preview = self._sync_planner.preview_from_manifests(sync_job, local_manifest, remote_manifest)
        if job.mode == DeploymentMode.UPLOAD_ONLY:
            sync_preview = self._preserve_remote_only(sync_preview)

        backup_directory = self.backup_directory(job)
        archive_name = self.archive_name(job)
        preview = DeploymentPreview(
            sync_preview=sync_preview,
            target_exists=target_exists,
            backup_directory=backup_directory,
            backup_archive_path=posixpath.join(backup_directory, archive_name),
            local_root=str(local_root),
            remote_root=remote_root,
        )
        preview = DeploymentPreview(
            sync_preview=preview.sync_preview,
            target_exists=preview.target_exists,
            backup_directory=preview.backup_directory,
            backup_archive_path=preview.backup_archive_path,
            local_root=preview.local_root,
            remote_root=preview.remote_root,
            digest=preview.calculated_digest(),
        )
        return OperationResult.success("Deployment preview built.", data=preview)

    def validate(self, job: DeploymentJob) -> OperationResult:
        local_root = Path(job.local_build_folder).expanduser()
        if not local_root.exists() or not local_root.is_dir():
            return OperationResult.failure("Deployment build folder must be an existing local folder.")
        if job.run_local_build:
            project_root = Path(job.resolved_project_folder()).expanduser()
            if not project_root.exists() or not project_root.is_dir():
                return OperationResult.failure("Local build project folder must be an existing folder.")
            if not job.local_build_command.strip():
                return OperationResult.failure("Local build is enabled but no build command is configured.")
        remote_root = normalize_remote_path(job.remote_target_folder)
        if not remote_root.startswith("/"):
            return OperationResult.failure("Remote deployment target must be an absolute path.")
        try:
            ensure_not_protected(remote_root)
        except Exception as exc:
            return OperationResult.failure(str(exc))
        if job.backup_directory:
            backup = normalize_remote_path(job.backup_directory)
            if not backup.startswith("/"):
                return OperationResult.failure("Backup directory override must be an absolute remote path.")
            try:
                ensure_not_protected(backup)
            except Exception as exc:
                return OperationResult.failure(str(exc))
            if backup == remote_root or backup.startswith(remote_root.rstrip("/") + "/"):
                return OperationResult.failure("Backup directory must be outside the deployment target.")
        if job.chmod_enabled and not re.fullmatch(r"[0-7]{3,4}", job.chmod_mode):
            return OperationResult.failure("Chmod mode must be a three or four digit octal value.")
        if not 1 <= int(job.backup_retention) <= 50:
            return OperationResult.failure("Backup retention must be between 1 and 50.")
        if not 1 <= int(job.release_retention) <= 50:
            return OperationResult.failure("Release retention must be between 1 and 50.")
        if not 1 <= int(job.history_retention) <= 1000:
            return OperationResult.failure("Deployment history retention must be between 1 and 1000.")
        health = job.health_check
        if not 1 <= int(health.attempts) <= 10:
            return OperationResult.failure("Health-check attempts must be between 1 and 10.")
        if not 1 <= int(health.timeout_seconds) <= 300:
            return OperationResult.failure("Health-check timeout must be between 1 and 300 seconds.")
        if not 0 <= int(health.interval_seconds) <= 60:
            return OperationResult.failure("Health-check retry interval must be between 0 and 60 seconds.")
        if not 100 <= int(health.minimum_status) <= int(health.maximum_status) <= 599:
            return OperationResult.failure("Health-check HTTP status range is invalid.")
        return OperationResult.success("Deployment settings are valid.")

    def backup_directory(self, job: DeploymentJob) -> str:
        if job.backup_directory:
            return normalize_remote_path(job.backup_directory)
        target = normalize_remote_path(job.remote_target_folder)
        parent = posixpath.dirname(target.rstrip("/")) or "/"
        return posixpath.join(parent, ".rfm-backups", job.id)

    def archive_name(self, job: DeploymentJob) -> str:
        target_name = posixpath.basename(normalize_remote_path(job.remote_target_folder).rstrip("/")) or "deployment"
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"{target_name}-{timestamp}.tar.gz"

    async def _local_manifest(self, root: Path, ignore_patterns: list[str]) -> list[SyncManifestEntry]:
        entries: list[SyncManifestEntry] = []
        visited = 0
        for directory, child_directories, filenames in os.walk(root):
            directory_path = Path(directory)
            child_directories[:] = [
                name
                for name in child_directories
                if not should_ignore((directory_path / name).relative_to(root).as_posix(), ignore_patterns or None)
            ]
            for filename in filenames:
                path = directory_path / filename
                relative = path.relative_to(root).as_posix()
                if should_ignore(relative, ignore_patterns or None):
                    continue
                stat = path.stat()
                entries.append(
                    SyncManifestEntry(
                        path=relative,
                        size=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
                    )
                )
                visited += 1
                if visited % 250 == 0:
                    await asyncio.sleep(0)
        return entries

    async def _remote_manifest(self, remote_ops, root: str, ignore_patterns: list[str]) -> OperationResult:  # type: ignore[no-untyped-def]
        try:
            entries: list[SyncManifestEntry] = []
            await self._collect_remote_files(remote_ops, root, root, ignore_patterns, entries)
            return OperationResult.success("Remote deployment manifest built.", data=entries)
        except Exception as exc:
            return OperationResult.failure(
                "Could not build remote deployment manifest.",
                technical_details=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )

    async def _collect_remote_files(
        self,
        remote_ops,
        root: str,
        current: str,
        ignore_patterns: list[str],
        entries: list[SyncManifestEntry],
    ) -> None:
        result = await remote_ops.list_dir(current, show_hidden=True)
        if not result.ok:
            raise RuntimeError(result.message)
        for item in result.data or []:
            relative = posixpath.relpath(item.path, root)
            if should_ignore(relative, ignore_patterns or None):
                continue
            if item.is_dir:
                await self._collect_remote_files(remote_ops, root, item.path, ignore_patterns, entries)
            elif item.is_file:
                entries.append(
                    SyncManifestEntry(
                        path=relative,
                        size=item.size,
                        modified_at=item.modified_at,
                    )
                )

    def _preserve_remote_only(self, preview: SyncPreview) -> SyncPreview:
        entries: list[SyncPlanEntry] = []
        skipped = list(preview.skipped)
        for entry in preview.entries:
            if entry.action == SyncAction.DELETE:
                entries.append(
                    SyncPlanEntry(
                        path=entry.path,
                        action=SyncAction.SKIP,
                        reason="Preserved by upload-only deployment mode",
                        source_size=entry.source_size,
                        destination_size=entry.destination_size,
                        source_side=entry.source_side,
                        target_side=entry.target_side,
                    )
                )
                skipped.append(entry.path)
            else:
                entries.append(entry)
        return SyncPreview(
            entries=entries,
            uploads=list(preview.uploads),
            downloads=list(preview.downloads),
            deletes=[],
            overwrites=list(preview.overwrites),
            conflicts=list(preview.conflicts),
            skipped=skipped,
            total_size=preview.total_size,
        )

    def _is_missing_result(self, result: OperationResult) -> bool:
        text = f"{result.message} {result.technical_details or ''}".lower()
        return any(token in text for token in ["not found", "no such file", "does not exist", "missing"])
