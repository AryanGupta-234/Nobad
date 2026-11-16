from __future__ import annotations

from pathlib import Path

import pytest

from core.result import OperationResult
from deployment.backup_manager import DeploymentBackup
from deployment.deployment_executor import DeploymentExecutor
from deployment.deployment_job import DeploymentExecutionPolicy, DeploymentJob, DeploymentPreview
from file_ops.conflict_policy import ConflictPolicy
from sync.diff_engine import SyncAction, SyncPlanEntry, SyncPreview, SyncTargetSide
from transfers.transfer_job import TransferDirection, TransferJob


class RecordingBuildRunner:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def run(self, command: str, *, working_directory, on_output=None) -> OperationResult:  # type: ignore[no-untyped-def]
        self.order.append("build")
        if on_output:
            on_output("password=<redacted>")
        return OperationResult.success("Built.")

    async def cancel(self) -> None:
        self.order.append("cancel-build")


class RecordingBackupManager:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.restored = False

    async def create_backup(self, connection, job, preview) -> OperationResult:  # type: ignore[no-untyped-def]
        self.order.append("backup")
        return OperationResult.success(
            "Backed up.",
            data=DeploymentBackup(True, "/backups/site.tar.gz", "tar.gz"),
        )

    async def restore_backup(self, connection, job, backup, *, run_id: str) -> OperationResult:  # type: ignore[no-untyped-def]
        self.order.append("rollback")
        self.restored = True
        return OperationResult.success("Restored.")

    async def prune_backups(self, connection, backup_directory: str, retention: int) -> OperationResult:  # type: ignore[no-untyped-def]
        self.order.append("prune")
        return OperationResult.success("Pruned.")


class RecordingTransferManager:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.jobs: list[TransferJob] = []

    def enqueue_upload_file(self, remote_ops, **kwargs) -> TransferJob:  # type: ignore[no-untyped-def]
        self.order.append("enqueue")
        assert kwargs["conflict_decision"].policy == ConflictPolicy.OVERWRITE
        job = TransferJob(
            None,
            None,
            str(kwargs["local_path"]),
            kwargs["remote_path"],
            TransferDirection.LOCAL_TO_SERVER,
            batch_id=kwargs["batch_id"],
        )
        self.jobs.append(job)
        return job

    async def run_until_idle(self) -> OperationResult:
        self.order.append("transfers")
        for job in self.jobs:
            job.mark_completed()
        return OperationResult.success("Idle.")

    async def cancel_batch(self, batch_id: str) -> OperationResult:
        return OperationResult.success("Cancelled.")


class RecordingRemoteOps:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def delete(self, path: str, *, recursive: bool = False) -> OperationResult:
        self.order.append("delete")
        return OperationResult.success("Deleted.")


class RecordingConnection:
    def __init__(self, order: list[str], *, fail_command: str | None = None) -> None:
        self.order = order
        self.fail_command = fail_command

    async def run_command(self, command: str, *, cwd: str | None = None) -> OperationResult:
        self.order.append(command)
        status = 1 if command == self.fail_command else 0
        return OperationResult.success(
            "Ran.",
            data={"stdout": "", "stderr": "command failed" if status else "", "exit_status": status},
        )


def make_preview(local_root: Path) -> DeploymentPreview:
    entries = [
        SyncPlanEntry(
            "index.html",
            SyncAction.UPLOAD,
            "Missing",
            source_size=4,
            source_side=SyncTargetSide.LOCAL,
            target_side=SyncTargetSide.REMOTE,
        ),
        SyncPlanEntry("old.txt", SyncAction.DELETE, "Remote only", target_side=SyncTargetSide.REMOTE),
    ]
    return DeploymentPreview(
        sync_preview=SyncPreview(
            entries=entries,
            uploads=["index.html"],
            deletes=["old.txt"],
            total_size=4,
        ),
        target_exists=True,
        backup_directory="/backups/job",
        backup_archive_path="/backups/job/site.tar.gz",
        local_root=str(local_root),
        remote_root="/var/www/site",
    )


@pytest.mark.asyncio
async def test_executor_orders_build_backup_transfers_delete_and_commands(tmp_path) -> None:
    (tmp_path / "index.html").write_text("site", encoding="utf-8")
    order: list[str] = []
    executor = DeploymentExecutor(
        backup_manager=RecordingBackupManager(order),
        build_runner=RecordingBuildRunner(order),
    )
    job = DeploymentJob(
        name="Site",
        local_project_folder=str(tmp_path),
        local_build_folder=str(tmp_path),
        remote_target_folder="/var/www/site",
        run_local_build=True,
        local_build_command="build",
        chmod_enabled=True,
        chmod_mode="755",
        post_deploy_command="post",
        cache_clear_command="cache",
        restart_command="restart",
    )

    result = await executor.execute(
        job,
        make_preview(tmp_path),
        RecordingConnection(order),
        RecordingRemoteOps(order),
        RecordingTransferManager(order),
        policy=DeploymentExecutionPolicy(confirmed=True),
    )

    assert result.ok
    assert order == [
        "build",
        "backup",
        "enqueue",
        "transfers",
        "delete",
        "chmod -R 755 .",
        "post",
        "cache",
        "restart",
        "prune",
    ]


@pytest.mark.asyncio
async def test_command_failure_triggers_rollback_and_preserves_original_error(tmp_path) -> None:
    (tmp_path / "index.html").write_text("site", encoding="utf-8")
    order: list[str] = []
    backups = RecordingBackupManager(order)
    executor = DeploymentExecutor(
        backup_manager=backups,
        build_runner=RecordingBuildRunner(order),
    )
    job = DeploymentJob(
        name="Site",
        local_build_folder=str(tmp_path),
        remote_target_folder="/var/www/site",
        post_deploy_command="fail",
    )

    result = await executor.execute(
        job,
        make_preview(tmp_path),
        RecordingConnection(order, fail_command="fail"),
        RecordingRemoteOps(order),
        RecordingTransferManager(order),
        policy=DeploymentExecutionPolicy(confirmed=True),
    )

    assert not result.ok
    assert backups.restored
    assert "Remote deployment command failed" in result.message
    assert result.data.rolled_back
