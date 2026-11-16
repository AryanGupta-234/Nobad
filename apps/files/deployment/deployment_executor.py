from __future__ import annotations

import asyncio
import posixpath
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from core.result import OperationResult, OperationStatus
from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from file_ops.safety import ensure_not_protected
from security.secret_scanner import redact_text
from sync.diff_engine import SyncAction
from transfers.transfer_job import TransferJob, TransferStatus

from deployment.backup_manager import BackupManager, DeploymentBackup
from deployment.deployment_job import (
    DeploymentArtifact,
    DeploymentArtifactKind,
    DeploymentExecutionPolicy,
    DeploymentExecutionResult,
    DeploymentJob,
    DeploymentPreview,
    DeploymentRunStatus,
    DeploymentStage,
    DeploymentStageEvent,
    DeploymentStrategy,
)
from deployment.deployment_lock import DeploymentLock, DeploymentLockManager
from deployment.deployment_planner import DeploymentPlanner
from deployment.health_checks import HealthCheckService
from deployment.local_build_runner import LocalBuildRunner
from deployment.release_manager import AtomicReleaseContext, ReleaseManager


class DeploymentExecutor:
    def __init__(
        self,
        *,
        backup_manager: BackupManager | None = None,
        build_runner: LocalBuildRunner | None = None,
        planner: DeploymentPlanner | None = None,
        lock_manager: DeploymentLockManager | None = None,
        release_manager: ReleaseManager | None = None,
        health_service: HealthCheckService | None = None,
    ) -> None:
        self.backup_manager = backup_manager or BackupManager()
        self.build_runner = build_runner or LocalBuildRunner()
        self.planner = planner or DeploymentPlanner()
        self.lock_manager = lock_manager or DeploymentLockManager()
        self.release_manager = release_manager or ReleaseManager()
        self.health_service = health_service or HealthCheckService()
        self._cancel_requested = False
        self._active_batch_id: str | None = None

    async def execute(
        self,
        job: DeploymentJob,
        preview: DeploymentPreview,
        connection,
        remote_ops,
        transfer_manager,
        *,
        policy: DeploymentExecutionPolicy | None = None,
        build_already_completed: bool = False,
        run_id: str | None = None,
        history_service=None,
        on_stage: Callable[[DeploymentStageEvent], None] | None = None,
        on_build_output: Callable[[str], None] | None = None,
    ) -> OperationResult:
        active_policy = policy or DeploymentExecutionPolicy()
        if not active_policy.confirmed:
            return OperationResult.failure("Deployment confirmation is required.")
        self._cancel_requested = False
        active_run_id = run_id or str(uuid4())
        batch_id = f"deployment-{job.id}-{active_run_id}"
        self._active_batch_id = batch_id
        lock: DeploymentLock | None = None
        final_result: OperationResult

        try:
            if job.profile_id:
                self._stage(
                    job,
                    active_run_id,
                    DeploymentStage.LOCKING,
                    "Acquiring deployment target lock.",
                    on_stage,
                    history_service,
                )
                lock_result = await self.lock_manager.acquire(
                    connection,
                    job,
                    active_run_id,
                    break_stale=active_policy.break_stale_lock,
                )
                if not lock_result.ok:
                    final_result = lock_result
                    return self._finish(job, active_run_id, final_result, history_service)
                lock = lock_result.data

            if preview.digest:
                self._stage(
                    job,
                    active_run_id,
                    DeploymentStage.PREVIEWING,
                    "Rebuilding deployment preview under the target lock.",
                    on_stage,
                    history_service,
                )
                fresh_result = await self.planner.build_preview(job, remote_ops)
                if not fresh_result.ok:
                    return self._finish(job, active_run_id, fresh_result, history_service)
                fresh_preview: DeploymentPreview = fresh_result.data
                if fresh_preview.calculated_digest() != preview.calculated_digest():
                    changed = self._failure(
                        job,
                        batch_id,
                        "Deployment preview changed after confirmation.",
                        run_id=active_run_id,
                        preview_changed=True,
                    )
                    changed.suggested_fix = "Review and confirm the fresh deployment preview before retrying."
                    return self._finish(job, active_run_id, changed, history_service)
                preview = fresh_preview

            if history_service and hasattr(history_service, "update_run_preview"):
                history_service.update_run_preview(active_run_id, preview)

            if job.run_local_build and not build_already_completed:
                self._stage(
                    job,
                    active_run_id,
                    DeploymentStage.BUILDING,
                    "Running local build.",
                    on_stage,
                    history_service,
                )

                def build_output(line: str) -> None:
                    if history_service:
                        history_service.append_stage_output(active_run_id, line)
                    if on_build_output:
                        on_build_output(line)

                build_result = await self.build_runner.run(
                    job.local_build_command,
                    working_directory=job.resolved_project_folder(),
                    on_output=build_output,
                )
                if not build_result.ok:
                    final_result = self._failure(
                        job,
                        batch_id,
                        build_result.message,
                        build_result.technical_details,
                        run_id=active_run_id,
                    )
                    return self._finish(job, active_run_id, final_result, history_service)
            self._raise_if_cancelled()

            if job.strategy == DeploymentStrategy.ATOMIC_RELEASE:
                final_result = await self._execute_atomic(
                    job,
                    preview,
                    connection,
                    remote_ops,
                    transfer_manager,
                    batch_id=batch_id,
                    run_id=active_run_id,
                    policy=active_policy,
                    history_service=history_service,
                    on_stage=on_stage,
                )
            else:
                final_result = await self._execute_in_place(
                    job,
                    preview,
                    connection,
                    remote_ops,
                    transfer_manager,
                    batch_id=batch_id,
                    run_id=active_run_id,
                    policy=active_policy,
                    history_service=history_service,
                    on_stage=on_stage,
                )
        except asyncio.CancelledError:
            await transfer_manager.cancel_batch(batch_id)
            final_result = self._failure(
                job,
                batch_id,
                "Deployment cancelled.",
                run_id=active_run_id,
                cancelled=True,
            )
        except _DeploymentCancelled:
            await transfer_manager.cancel_batch(batch_id)
            final_result = self._failure(
                job,
                batch_id,
                "Deployment cancelled.",
                run_id=active_run_id,
                cancelled=True,
            )
        except Exception as exc:
            final_result = self._failure(
                job,
                batch_id,
                "Deployment failed.",
                f"{type(exc).__name__}: {exc}",
                run_id=active_run_id,
            )
        finally:
            if lock is not None:
                await self.lock_manager.release(connection, lock)
            self._active_batch_id = None

        return self._finish(job, active_run_id, final_result, history_service)

    async def cancel(self, transfer_manager) -> OperationResult:  # type: ignore[no-untyped-def]
        self._cancel_requested = True
        await self.build_runner.cancel()
        if self._active_batch_id:
            return await transfer_manager.cancel_batch(self._active_batch_id)
        return OperationResult.success("Deployment cancellation requested.")

    async def _execute_in_place(
        self,
        job: DeploymentJob,
        preview: DeploymentPreview,
        connection,
        remote_ops,
        transfer_manager,
        *,
        batch_id: str,
        run_id: str,
        policy: DeploymentExecutionPolicy,
        history_service,
        on_stage,
    ) -> OperationResult:
        backup: DeploymentBackup | None = None
        try:
            self._stage(job, run_id, DeploymentStage.BACKING_UP, "Creating remote backup.", on_stage, history_service)
            backup_result = await self.backup_manager.create_backup(connection, job, preview)
            if not backup_result.ok:
                return self._failure(
                    job,
                    batch_id,
                    backup_result.message,
                    backup_result.technical_details,
                    run_id=run_id,
                )
            backup = backup_result.data
            self._record_backup_artifact(job, run_id, backup, history_service)
            self._raise_if_cancelled()

            transfer_result = await self._transfer_and_delete(
                job,
                preview,
                connection,
                remote_ops,
                transfer_manager,
                batch_id=batch_id,
                run_id=run_id,
                remote_root=preview.remote_root,
                history_service=history_service,
                on_stage=on_stage,
            )
            if not transfer_result.ok:
                return await self._rollback_in_place_failure(
                    job,
                    batch_id,
                    connection,
                    backup,
                    run_id,
                    transfer_result.message,
                    transfer_result.technical_details,
                    policy,
                    history_service,
                    on_stage,
                    cancelled=transfer_result.status == OperationStatus.CANCELLED,
                )

            command_result = await self._run_stage_commands(
                job,
                connection,
                preview.remote_root,
                self._in_place_commands(job),
                run_id,
                history_service,
                on_stage,
            )
            if not command_result.ok:
                return await self._rollback_in_place_failure(
                    job,
                    batch_id,
                    connection,
                    backup,
                    run_id,
                    command_result.message,
                    command_result.technical_details,
                    policy,
                    history_service,
                    on_stage,
                )

            health_result = await self._health_check(
                job,
                connection,
                preview.remote_root,
                run_id,
                history_service,
                on_stage,
            )
            if not health_result.ok:
                return await self._rollback_in_place_failure(
                    job,
                    batch_id,
                    connection,
                    backup,
                    run_id,
                    health_result.message,
                    health_result.technical_details,
                    policy,
                    history_service,
                    on_stage,
                    health_check=health_result.data,
                )

            self._stage(
                job,
                run_id,
                DeploymentStage.PRUNING_BACKUPS,
                "Pruning old deployment backups.",
                on_stage,
                history_service,
            )
            prune_result = await self.backup_manager.prune_backups(
                connection,
                preview.backup_directory,
                job.backup_retention,
            )
            warnings = [] if prune_result.ok else [prune_result.message]
            if prune_result.ok and history_service:
                history_service.apply_artifact_retention(
                    job.id,
                    DeploymentArtifactKind.BACKUP,
                    keep=job.backup_retention,
                )
            self._stage(job, run_id, DeploymentStage.COMPLETED, "Deployment completed.", on_stage, history_service)
            return OperationResult.success(
                "Deployment completed.",
                data=DeploymentExecutionResult(
                    deployment_id=job.id,
                    batch_id=batch_id,
                    run_id=run_id,
                    strategy=job.strategy,
                    uploads=preview.uploads,
                    overwrites=preview.overwrites,
                    deletes=preview.deletes,
                    backup_path=backup.archive_path if backup else None,
                    health_check=health_result.data,
                ),
                warnings=warnings + list(health_result.warnings),
            )
        except _DeploymentCancelled:
            if backup is not None:
                return await self._rollback_in_place_failure(
                    job,
                    batch_id,
                    connection,
                    backup,
                    run_id,
                    "Deployment cancelled.",
                    None,
                    policy,
                    history_service,
                    on_stage,
                    cancelled=True,
                )
            raise

    async def _execute_atomic(
        self,
        job: DeploymentJob,
        preview: DeploymentPreview,
        connection,
        remote_ops,
        transfer_manager,
        *,
        batch_id: str,
        run_id: str,
        policy: DeploymentExecutionPolicy,
        history_service,
        on_stage,
    ) -> OperationResult:
        context: AtomicReleaseContext | None = None
        adoption_backup: DeploymentBackup | None = None
        inspection = await self.release_manager.inspect_target(connection, job)
        if not inspection.ok:
            return self._failure(
                job,
                batch_id,
                inspection.message,
                inspection.technical_details,
                run_id=run_id,
            )
        if inspection.data.get("kind") == "directory":
            self._stage(
                job,
                run_id,
                DeploymentStage.BACKING_UP,
                "Backing up the target before atomic adoption.",
                on_stage,
                history_service,
            )
            backup_result = await self.backup_manager.create_backup(connection, job, preview)
            if not backup_result.ok:
                return self._failure(
                    job,
                    batch_id,
                    backup_result.message,
                    backup_result.technical_details,
                    run_id=run_id,
                )
            adoption_backup = backup_result.data
            self._record_backup_artifact(job, run_id, adoption_backup, history_service)

        try:
            self._stage(
                job,
                run_id,
                DeploymentStage.PREPARING_RELEASE,
                "Preparing atomic release staging.",
                on_stage,
                history_service,
            )
            prepared = await self.release_manager.prepare(connection, job, run_id)
            if not prepared.ok:
                return self._failure(
                    job,
                    batch_id,
                    prepared.message,
                    prepared.technical_details,
                    run_id=run_id,
                )
            context = prepared.data
            if context.adopted_release_path and history_service:
                history_service.add_artifact(
                    DeploymentArtifact(
                        run_id=run_id,
                        job_id=job.id,
                        profile_id=job.profile_id,
                        kind=DeploymentArtifactKind.RELEASE,
                        path=context.adopted_release_path,
                        format="directory",
                        active=True,
                        metadata={"adopted": True},
                    )
                )
            self._raise_if_cancelled()

            transfer_result = await self._transfer_and_delete(
                job,
                preview,
                connection,
                remote_ops,
                transfer_manager,
                batch_id=batch_id,
                run_id=run_id,
                remote_root=context.staging_path,
                history_service=history_service,
                on_stage=on_stage,
            )
            if not transfer_result.ok:
                return await self._rollback_atomic_failure(
                    job,
                    batch_id,
                    connection,
                    context,
                    run_id,
                    transfer_result.message,
                    transfer_result.technical_details,
                    policy,
                    history_service,
                    on_stage,
                    cancelled=transfer_result.status == OperationStatus.CANCELLED,
                )

            pre_switch = await self._run_stage_commands(
                job,
                connection,
                context.staging_path,
                self._pre_switch_commands(job),
                run_id,
                history_service,
                on_stage,
            )
            if not pre_switch.ok:
                return await self._rollback_atomic_failure(
                    job,
                    batch_id,
                    connection,
                    context,
                    run_id,
                    pre_switch.message,
                    pre_switch.technical_details,
                    policy,
                    history_service,
                    on_stage,
                )

            self._stage(
                job,
                run_id,
                DeploymentStage.SWITCHING_RELEASE,
                "Switching the active release.",
                on_stage,
                history_service,
            )
            switched = await self.release_manager.switch(connection, context)
            if not switched.ok:
                return await self._rollback_atomic_failure(
                    job,
                    batch_id,
                    connection,
                    context,
                    run_id,
                    switched.message,
                    switched.technical_details,
                    policy,
                    history_service,
                    on_stage,
                )
            if history_service:
                history_service.add_artifact(
                    DeploymentArtifact(
                        run_id=run_id,
                        job_id=job.id,
                        profile_id=job.profile_id,
                        kind=DeploymentArtifactKind.RELEASE,
                        path=context.release_path,
                        format="directory",
                        active=True,
                        metadata={"previous_release_path": context.previous_release_path},
                    )
                )

            post_switch = await self._run_stage_commands(
                job,
                connection,
                preview.remote_root,
                self._post_switch_commands(job),
                run_id,
                history_service,
                on_stage,
            )
            if not post_switch.ok:
                return await self._rollback_atomic_failure(
                    job,
                    batch_id,
                    connection,
                    context,
                    run_id,
                    post_switch.message,
                    post_switch.technical_details,
                    policy,
                    history_service,
                    on_stage,
                )

            health_result = await self._health_check(
                job,
                connection,
                preview.remote_root,
                run_id,
                history_service,
                on_stage,
            )
            if not health_result.ok:
                return await self._rollback_atomic_failure(
                    job,
                    batch_id,
                    connection,
                    context,
                    run_id,
                    health_result.message,
                    health_result.technical_details,
                    policy,
                    history_service,
                    on_stage,
                    health_check=health_result.data,
                )

            self._stage(
                job,
                run_id,
                DeploymentStage.PRUNING_RELEASES,
                "Pruning old atomic releases.",
                on_stage,
                history_service,
            )
            prune = await self.release_manager.prune(
                connection,
                job,
                active_path=context.release_path,
                previous_path=context.previous_release_path,
            )
            warnings = [] if prune.ok else [prune.message]
            if prune.ok and history_service:
                history_service.apply_artifact_retention(
                    job.id,
                    DeploymentArtifactKind.RELEASE,
                    keep=job.release_retention,
                    protected_paths={
                        path
                        for path in [context.release_path, context.previous_release_path]
                        if path
                    },
                )
            self._stage(job, run_id, DeploymentStage.COMPLETED, "Deployment completed.", on_stage, history_service)
            return OperationResult.success(
                "Atomic deployment completed.",
                data=DeploymentExecutionResult(
                    deployment_id=job.id,
                    batch_id=batch_id,
                    run_id=run_id,
                    strategy=job.strategy,
                    uploads=preview.uploads,
                    overwrites=preview.overwrites,
                    deletes=preview.deletes,
                    backup_path=adoption_backup.archive_path if adoption_backup else None,
                    release_path=context.release_path,
                    previous_release_path=context.previous_release_path,
                    health_check=health_result.data,
                ),
                warnings=warnings + list(health_result.warnings),
            )
        except _DeploymentCancelled:
            if context is not None:
                return await self._rollback_atomic_failure(
                    job,
                    batch_id,
                    connection,
                    context,
                    run_id,
                    "Deployment cancelled.",
                    None,
                    policy,
                    history_service,
                    on_stage,
                    cancelled=True,
                )
            raise

    async def _transfer_and_delete(
        self,
        job: DeploymentJob,
        preview: DeploymentPreview,
        connection,
        remote_ops,
        transfer_manager,
        *,
        batch_id: str,
        run_id: str,
        remote_root: str,
        history_service,
        on_stage,
    ) -> OperationResult:
        self._stage(
            job,
            run_id,
            DeploymentStage.TRANSFERRING,
            "Queueing deployment uploads.",
            on_stage,
            history_service,
        )
        transfer_jobs = self._enqueue_transfers(
            preview,
            remote_ops,
            transfer_manager,
            batch_id,
            remote_root=remote_root,
        )
        if transfer_jobs:
            await transfer_manager.run_until_idle()
            incomplete = [item for item in transfer_jobs if item.status != TransferStatus.COMPLETED]
            if incomplete:
                detail = incomplete[0].error_message or f"Transfer ended as {incomplete[0].status.value}."
                return OperationResult(
                    status=(
                        OperationStatus.CANCELLED
                        if any(item.status == TransferStatus.CANCELLED for item in incomplete)
                        else OperationStatus.FAILED
                    ),
                    message="Deployment transfers did not all complete.",
                    technical_details=detail,
                )
        self._raise_if_cancelled()
        self._stage(
            job,
            run_id,
            DeploymentStage.DELETING,
            "Applying mirror deletions.",
            on_stage,
            history_service,
        )
        return await self._apply_deletes(preview, remote_ops, remote_root=remote_root)

    def _enqueue_transfers(
        self,
        preview: DeploymentPreview,
        remote_ops,
        transfer_manager,
        batch_id: str,
        *,
        remote_root: str,
    ) -> list[TransferJob]:
        jobs: list[TransferJob] = []
        local_root = Path(preview.local_root)
        for entry in preview.sync_preview.entries:
            if entry.action not in {SyncAction.UPLOAD, SyncAction.OVERWRITE}:
                continue
            jobs.append(
                transfer_manager.enqueue_upload_file(
                    remote_ops,
                    local_path=local_root / Path(entry.path),
                    remote_path=posixpath.join(remote_root, entry.path),
                    batch_id=batch_id,
                    conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
                )
            )
        return jobs

    async def _apply_deletes(self, preview: DeploymentPreview, remote_ops, *, remote_root: str) -> OperationResult:  # type: ignore[no-untyped-def]
        for entry in preview.sync_preview.entries:
            if entry.action != SyncAction.DELETE:
                continue
            target = posixpath.normpath(posixpath.join(remote_root, entry.path))
            ensure_not_protected(target)
            result = await remote_ops.delete(target, recursive=False)
            if not result.ok:
                return OperationResult.failure(
                    f"Could not delete remote deployment file: {entry.path}",
                    technical_details=result.technical_details,
                )
        return OperationResult.success("Deployment deletions completed.")

    async def _run_stage_commands(
        self,
        job: DeploymentJob,
        connection,
        cwd: str,
        commands: list[tuple[DeploymentStage, str]],
        run_id: str,
        history_service,
        on_stage,
    ) -> OperationResult:
        for stage, command in commands:
            self._raise_if_cancelled()
            self._stage(
                job,
                run_id,
                stage,
                f"Running {stage.value.replace('_', ' ')} command.",
                on_stage,
                history_service,
            )
            result = await self._run_command(connection, command, cwd=cwd)
            if history_service:
                data = result.data if isinstance(result.data, dict) else {}
                output = "\n".join(
                    part for part in [str(data.get("stdout") or ""), str(data.get("stderr") or "")] if part
                )
                if output:
                    history_service.append_stage_output(run_id, output)
            if not result.ok:
                return result
        return OperationResult.success("Deployment commands completed.")

    async def _health_check(
        self,
        job: DeploymentJob,
        connection,
        cwd: str,
        run_id: str,
        history_service,
        on_stage,
    ) -> OperationResult:
        self._stage(
            job,
            run_id,
            DeploymentStage.HEALTH_CHECK,
            "Running deployment health checks.",
            on_stage,
            history_service,
        )
        result = await self.health_service.run(connection, job.health_check, cwd=cwd)
        if history_service:
            details = [
                result.message,
                result.technical_details or "",
                *result.warnings,
            ]
            history_service.append_stage_output(
                run_id,
                "\n".join(part for part in details if part),
            )
        return result

    def _in_place_commands(self, job: DeploymentJob) -> list[tuple[DeploymentStage, str]]:
        return self._pre_switch_commands(job) + self._post_switch_commands(job)

    def _pre_switch_commands(self, job: DeploymentJob) -> list[tuple[DeploymentStage, str]]:
        commands: list[tuple[DeploymentStage, str]] = []
        if job.chmod_enabled:
            commands.append((DeploymentStage.CHMOD, f"chmod -R {job.chmod_mode} ."))
        if job.post_deploy_command.strip():
            commands.append((DeploymentStage.POST_DEPLOY, job.post_deploy_command.strip()))
        return commands

    def _post_switch_commands(self, job: DeploymentJob) -> list[tuple[DeploymentStage, str]]:
        commands: list[tuple[DeploymentStage, str]] = []
        if job.cache_clear_command.strip():
            commands.append((DeploymentStage.CACHE_CLEAR, job.cache_clear_command.strip()))
        if job.restart_command.strip():
            commands.append((DeploymentStage.RESTART, job.restart_command.strip()))
        return commands

    async def _run_command(self, connection, command: str, *, cwd: str) -> OperationResult:  # type: ignore[no-untyped-def]
        result = await connection.run_command(command, cwd=cwd)
        data = result.data if isinstance(result.data, dict) else {}
        if result.ok and int(data.get("exit_status", 1)) == 0:
            return OperationResult.success("Remote deployment command completed.", data=data)
        details = redact_text(str(data.get("stderr") or result.technical_details or "")).strip() or None
        return OperationResult.failure("Remote deployment command failed.", technical_details=details)

    async def _rollback_in_place_failure(
        self,
        job: DeploymentJob,
        batch_id: str,
        connection,
        backup: DeploymentBackup,
        run_id: str,
        message: str,
        technical_details: str | None,
        policy: DeploymentExecutionPolicy,
        history_service,
        on_stage,
        *,
        cancelled: bool = False,
        health_check=None,
    ) -> OperationResult:
        if not policy.rollback_on_failure:
            return self._failure(
                job,
                batch_id,
                message,
                technical_details,
                run_id=run_id,
                cancelled=cancelled,
            )
        self._stage(
            job,
            run_id,
            DeploymentStage.ROLLING_BACK,
            "Restoring deployment backup.",
            on_stage,
            history_service,
            "warning",
        )
        rollback = await self.backup_manager.restore_backup(connection, job, backup, run_id=run_id)
        return self._rollback_result(
            job,
            batch_id,
            run_id,
            message,
            technical_details,
            rollback,
            cancelled=cancelled,
            backup_path=backup.archive_path,
            health_check=health_check,
        )

    async def _rollback_atomic_failure(
        self,
        job: DeploymentJob,
        batch_id: str,
        connection,
        context: AtomicReleaseContext,
        run_id: str,
        message: str,
        technical_details: str | None,
        policy: DeploymentExecutionPolicy,
        history_service,
        on_stage,
        *,
        cancelled: bool = False,
        health_check=None,
    ) -> OperationResult:
        if not policy.rollback_on_failure:
            return self._failure(
                job,
                batch_id,
                message,
                technical_details,
                run_id=run_id,
                cancelled=cancelled,
            )
        self._stage(
            job,
            run_id,
            DeploymentStage.ROLLING_BACK,
            "Switching back to the previous atomic release.",
            on_stage,
            history_service,
            "warning",
        )
        rollback = await self.release_manager.rollback(connection, context)
        if rollback.ok and history_service:
            history_service.set_active_release(job.id, context.previous_release_path)
        return self._rollback_result(
            job,
            batch_id,
            run_id,
            message,
            technical_details,
            rollback,
            cancelled=cancelled,
            release_path=context.release_path,
            previous_release_path=context.previous_release_path,
            health_check=health_check,
        )

    def _rollback_result(
        self,
        job: DeploymentJob,
        batch_id: str,
        run_id: str,
        message: str,
        technical_details: str | None,
        rollback: OperationResult,
        *,
        cancelled: bool,
        backup_path: str | None = None,
        release_path: str | None = None,
        previous_release_path: str | None = None,
        health_check=None,
    ) -> OperationResult:
        result = self._failure(
            job,
            batch_id,
            f"{message} Automatic rollback {'completed' if rollback.ok else 'failed'}.",
            technical_details,
            run_id=run_id,
            cancelled=cancelled,
        )
        result.data = DeploymentExecutionResult(
            deployment_id=job.id,
            batch_id=batch_id,
            run_id=run_id,
            strategy=job.strategy,
            backup_path=backup_path,
            release_path=release_path,
            previous_release_path=previous_release_path,
            rolled_back=rollback.ok,
            rollback_error=None if rollback.ok else rollback.message,
            cancelled=cancelled,
            health_check=health_check,
        )
        if not rollback.ok:
            result.warnings.append(f"Rollback failure: {rollback.message}")
            if rollback.technical_details:
                result.warnings.append(rollback.technical_details)
        return result

    def _failure(
        self,
        job: DeploymentJob,
        batch_id: str,
        message: str,
        technical_details: str | None = None,
        *,
        run_id: str | None = None,
        cancelled: bool = False,
        preview_changed: bool = False,
    ) -> OperationResult:
        return OperationResult(
            status=OperationStatus.CANCELLED if cancelled else OperationStatus.FAILED,
            message=message,
            technical_details=technical_details,
            data=DeploymentExecutionResult(
                deployment_id=job.id,
                batch_id=batch_id,
                run_id=run_id,
                strategy=job.strategy,
                cancelled=cancelled,
                preview_changed=preview_changed,
            ),
        )

    def _record_backup_artifact(self, job, run_id, backup, history_service) -> None:  # type: ignore[no-untyped-def]
        if not history_service or not backup.archive_path:
            return
        history_service.add_artifact(
            DeploymentArtifact(
                run_id=run_id,
                job_id=job.id,
                profile_id=job.profile_id,
                kind=DeploymentArtifactKind.BACKUP,
                path=backup.archive_path,
                format=backup.archive_format or "",
            )
        )

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested:
            raise _DeploymentCancelled

    def _stage(
        self,
        job: DeploymentJob,
        run_id: str,
        stage: DeploymentStage,
        message: str,
        callback,
        history_service,
        level: str = "info",
    ) -> None:
        event = DeploymentStageEvent(job.id, stage, message, level, run_id)
        if history_service:
            history_service.begin_stage(event)
        if callback:
            callback(event)

    def _finish(self, job: DeploymentJob, run_id: str, result: OperationResult, history_service) -> OperationResult:
        if not history_service:
            return result
        data = result.data if isinstance(result.data, DeploymentExecutionResult) else None
        if result.ok:
            status = DeploymentRunStatus.SUCCESS
        elif data and data.rollback_error:
            status = DeploymentRunStatus.ROLLBACK_FAILED
        elif data and data.rolled_back:
            status = DeploymentRunStatus.ROLLED_BACK
        elif result.status == OperationStatus.CANCELLED:
            status = DeploymentRunStatus.CANCELLED
        else:
            status = DeploymentRunStatus.FAILED
        health = data.health_check if data else None
        artifact_path = None
        if data:
            artifact_path = data.release_path or data.backup_path
        history_service.finish_run(
            run_id,
            status=status,
            message=result.message,
            health_ok=health.ok if health else None,
            artifact_path=artifact_path,
            rolled_back=bool(data and data.rolled_back),
            rollback_error=data.rollback_error if data else None,
            retention=job.history_retention,
        )
        return result


class _DeploymentCancelled(Exception):
    pass
