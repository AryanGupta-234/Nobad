from __future__ import annotations

import posixpath
from datetime import UTC, datetime

from core.result import OperationResult, OperationStatus
from security.secret_scanner import redact_text
from sync.diff_engine import SyncPreview

from deployment.backup_manager import BackupManager, DeploymentBackup
from deployment.deployment_job import (
    DeploymentArtifact,
    DeploymentArtifactKind,
    DeploymentExecutionResult,
    DeploymentJob,
    DeploymentPreview,
    DeploymentRunStatus,
    DeploymentStage,
    DeploymentStageEvent,
    DeploymentStrategy,
)
from deployment.deployment_lock import DeploymentLockManager
from deployment.health_checks import HealthCheckService
from deployment.release_manager import ReleaseManager


class ManualRollbackService:
    def __init__(
        self,
        *,
        backup_manager: BackupManager | None = None,
        release_manager: ReleaseManager | None = None,
        health_service: HealthCheckService | None = None,
        lock_manager: DeploymentLockManager | None = None,
    ) -> None:
        self.backup_manager = backup_manager or BackupManager()
        self.release_manager = release_manager or ReleaseManager()
        self.health_service = health_service or HealthCheckService()
        self.lock_manager = lock_manager or DeploymentLockManager()

    async def rollback(
        self,
        job: DeploymentJob,
        artifact: DeploymentArtifact,
        connection,
        *,
        run_id: str,
        break_stale_lock: bool = False,
        history_service=None,
        on_stage=None,
    ) -> OperationResult:
        lock = None
        try:
            self._stage(job, run_id, DeploymentStage.LOCKING, "Acquiring deployment rollback lock.", on_stage, history_service)
            lock_result = await self.lock_manager.acquire(
                connection,
                job,
                run_id,
                break_stale=break_stale_lock,
            )
            if not lock_result.ok:
                return lock_result
            lock = lock_result.data
            if job.strategy == DeploymentStrategy.ATOMIC_RELEASE:
                result = await self._rollback_atomic(
                    job,
                    artifact,
                    connection,
                    run_id=run_id,
                    history_service=history_service,
                    on_stage=on_stage,
                )
            else:
                result = await self._rollback_in_place(
                    job,
                    artifact,
                    connection,
                    run_id=run_id,
                    history_service=history_service,
                    on_stage=on_stage,
                )
            return result
        finally:
            await self.lock_manager.release(connection, lock)

    async def scan_artifacts(self, job: DeploymentJob, connection) -> OperationResult:  # type: ignore[no-untyped-def]
        artifacts: list[DeploymentArtifact] = []
        backup_dir = self._backup_directory(job)
        backups = await self.backup_manager.list_backups(connection, backup_dir)
        if backups.ok:
            for item in backups.data:
                artifacts.append(
                    DeploymentArtifact(
                        run_id=None,
                        job_id=job.id,
                        profile_id=job.profile_id,
                        kind=DeploymentArtifactKind.BACKUP,
                        path=item["path"],
                        format=item["format"],
                        imported=True,
                        metadata={"size": item["size"], "timestamp": item["timestamp"]},
                    )
                )
        if job.strategy == DeploymentStrategy.ATOMIC_RELEASE:
            inspected = await self.release_manager.inspect_target(connection, job)
            active = inspected.data.get("resolved") if inspected.ok else None
            releases = await self.release_manager.list_releases(connection, job)
            if releases.ok:
                for path in releases.data:
                    artifacts.append(
                        DeploymentArtifact(
                            run_id=None,
                            job_id=job.id,
                            profile_id=job.profile_id,
                            kind=DeploymentArtifactKind.RELEASE,
                            path=path,
                            format="directory",
                            active=path == active,
                            imported=True,
                        )
                    )
        return OperationResult.success("Deployment artifacts scanned.", data=artifacts)

    async def _rollback_atomic(
        self,
        job: DeploymentJob,
        artifact: DeploymentArtifact,
        connection,
        *,
        run_id: str,
        history_service,
        on_stage,
    ) -> OperationResult:
        if artifact.kind != DeploymentArtifactKind.RELEASE:
            return OperationResult.failure("Atomic rollback requires a release artifact.")
        inspection = await self.release_manager.inspect_target(connection, job)
        if not inspection.ok:
            return inspection
        previous = inspection.data.get("resolved")
        if not previous:
            return OperationResult.failure("The atomic target has no currently active release.")
        self._stage(job, run_id, DeploymentStage.SWITCHING_RELEASE, "Switching to selected historical release.", on_stage, history_service)
        switched = await self.release_manager.switch_to(connection, job.remote_target_folder, artifact.path)
        if not switched.ok:
            return switched
        verification = await self._post_rollback_verification(job, connection, run_id, history_service, on_stage)
        if verification.ok:
            if history_service:
                history_service.set_active_release(job.id, artifact.path)
            return OperationResult.success(
                "Manual atomic rollback completed.",
                data=DeploymentExecutionResult(
                    deployment_id=job.id,
                    batch_id=f"rollback-{run_id}",
                    run_id=run_id,
                    strategy=job.strategy,
                    release_path=artifact.path,
                    previous_release_path=previous,
                    health_check=verification.data,
                    rolled_back=True,
                ),
            )
        restored = await self.release_manager.switch_to(connection, job.remote_target_folder, previous)
        if restored.ok and history_service:
            history_service.set_active_release(job.id, previous)
        return self._rollback_verification_failure(
            job,
            run_id,
            verification,
            restored,
            artifact.path,
            previous,
        )

    async def _rollback_in_place(
        self,
        job: DeploymentJob,
        artifact: DeploymentArtifact,
        connection,
        *,
        run_id: str,
        history_service,
        on_stage,
    ) -> OperationResult:
        if artifact.kind != DeploymentArtifactKind.BACKUP:
            return OperationResult.failure("In-place rollback requires an archive backup.")
        safety_path = posixpath.join(
            self._backup_directory(job),
            f"pre-rollback-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz",
        )
        safety_preview = DeploymentPreview(
            sync_preview=SyncPreview(),
            target_exists=True,
            backup_directory=posixpath.dirname(safety_path),
            backup_archive_path=safety_path,
            local_root="",
            remote_root=job.remote_target_folder,
        )
        self._stage(job, run_id, DeploymentStage.BACKING_UP, "Preserving the currently active deployment.", on_stage, history_service)
        safety = await self.backup_manager.create_backup(connection, job, safety_preview)
        if not safety.ok:
            return safety
        selected = DeploymentBackup(True, artifact.path, artifact.format)
        self._stage(job, run_id, DeploymentStage.ROLLING_BACK, "Restoring selected deployment backup.", on_stage, history_service)
        restored = await self.backup_manager.restore_backup(connection, job, selected, run_id=run_id)
        if not restored.ok:
            return restored
        verification = await self._post_rollback_verification(job, connection, run_id, history_service, on_stage)
        if verification.ok:
            if history_service and safety.data.archive_path:
                history_service.add_artifact(
                    DeploymentArtifact(
                        run_id=run_id,
                        job_id=job.id,
                        profile_id=job.profile_id,
                        kind=DeploymentArtifactKind.BACKUP,
                        path=safety.data.archive_path,
                        format=safety.data.archive_format or "",
                    )
                )
            return OperationResult.success(
                "Manual in-place rollback completed.",
                data=DeploymentExecutionResult(
                    deployment_id=job.id,
                    batch_id=f"rollback-{run_id}",
                    run_id=run_id,
                    strategy=job.strategy,
                    backup_path=artifact.path,
                    health_check=verification.data,
                    rolled_back=True,
                ),
            )
        undo = await self.backup_manager.restore_backup(connection, job, safety.data, run_id=f"{run_id}-undo")
        return self._rollback_verification_failure(
            job,
            run_id,
            verification,
            undo,
            artifact.path,
            safety.data.archive_path,
        )

    async def _post_rollback_verification(
        self,
        job: DeploymentJob,
        connection,
        run_id: str,
        history_service,
        on_stage,
    ) -> OperationResult:
        for stage, command in [
            (DeploymentStage.CACHE_CLEAR, job.cache_clear_command),
            (DeploymentStage.RESTART, job.restart_command),
        ]:
            if not command.strip():
                continue
            self._stage(job, run_id, stage, f"Running {stage.value.replace('_', ' ')} after rollback.", on_stage, history_service)
            result = await connection.run_command(command.strip(), cwd=job.remote_target_folder)
            data = result.data if isinstance(result.data, dict) else {}
            if not result.ok or int(data.get("exit_status", 1)) != 0:
                return OperationResult.failure(
                    "Post-rollback command failed.",
                    technical_details=redact_text(str(data.get("stderr") or result.technical_details or "")) or None,
                )
        self._stage(job, run_id, DeploymentStage.HEALTH_CHECK, "Verifying the restored deployment.", on_stage, history_service)
        return await self.health_service.run(connection, job.health_check, cwd=job.remote_target_folder)

    def _rollback_verification_failure(
        self,
        job: DeploymentJob,
        run_id: str,
        verification: OperationResult,
        restored: OperationResult,
        selected_path: str,
        previous_path: str | None,
    ) -> OperationResult:
        rollback_error = None if restored.ok else restored.message
        result = OperationResult(
            status=OperationStatus.FAILED,
            message=(
                "Manual rollback verification failed; the previously active deployment was restored."
                if restored.ok
                else "Manual rollback verification failed and restoring the previous deployment also failed."
            ),
            technical_details=verification.technical_details,
            data=DeploymentExecutionResult(
                deployment_id=job.id,
                batch_id=f"rollback-{run_id}",
                run_id=run_id,
                strategy=job.strategy,
                release_path=selected_path if job.strategy == DeploymentStrategy.ATOMIC_RELEASE else None,
                previous_release_path=previous_path,
                backup_path=selected_path if job.strategy == DeploymentStrategy.IN_PLACE else None,
                rolled_back=restored.ok,
                rollback_error=rollback_error,
                health_check=getattr(verification, "data", None),
            ),
        )
        if rollback_error:
            result.warnings.append(f"Rollback recovery failure: {rollback_error}")
        return result

    def _backup_directory(self, job: DeploymentJob) -> str:
        if job.backup_directory:
            return job.backup_directory
        parent = posixpath.dirname(job.remote_target_folder.rstrip("/")) or "/"
        return posixpath.join(parent, ".rfm-backups", job.id)

    def _stage(self, job, run_id, stage, message, callback, history_service, level="info") -> None:  # type: ignore[no-untyped-def]
        event = DeploymentStageEvent(job.id, stage, message, level, run_id)
        if history_service:
            history_service.begin_stage(event)
        if callback:
            callback(event)
