from __future__ import annotations

import pytest

from core.result import OperationResult
from deployment.backup_manager import BackupManager
from deployment.deployment_job import DeploymentJob, DeploymentPreview
from sync.diff_engine import SyncPreview


class FakeConnection:
    def __init__(self, tool: str = "tar") -> None:
        self.tool = tool
        self.commands: list[str] = []

    async def run_command(self, command: str, *, cwd: str | None = None) -> OperationResult:
        self.commands.append(command)
        if "command -v tar" in command:
            status = 127 if self.tool == "none" else 0
            output = "" if self.tool == "none" else self.tool
            return OperationResult.success(
                "Command completed.",
                data={"stdout": output, "stderr": "missing" if status else "", "exit_status": status},
            )
        return OperationResult.success(
            "Command completed.",
            data={"stdout": "", "stderr": "", "exit_status": 0},
        )


def preview(*, target_exists: bool = True) -> DeploymentPreview:
    return DeploymentPreview(
        sync_preview=SyncPreview(),
        target_exists=target_exists,
        backup_directory="/var/www/.rfm-backups/job",
        backup_archive_path="/var/www/.rfm-backups/job/site.tar.gz",
        local_root="/tmp/site",
        remote_root="/var/www/site",
    )


@pytest.mark.asyncio
async def test_backup_prefers_tar_and_uses_quoted_target() -> None:
    connection = FakeConnection("tar")
    job = DeploymentJob(name="Site", remote_target_folder="/var/www/my site")

    result = await BackupManager().create_backup(connection, job, preview())

    assert result.ok
    assert result.data.archive_format == "tar.gz"
    assert "tar -czf" in connection.commands[-1]
    assert "'./my site'" in connection.commands[-1]


@pytest.mark.asyncio
async def test_backup_falls_back_to_zip_and_blocks_without_tools() -> None:
    zip_connection = FakeConnection("zip")
    missing_connection = FakeConnection("none")
    job = DeploymentJob(name="Site", remote_target_folder="/var/www/site")

    zip_result = await BackupManager().create_backup(zip_connection, job, preview())
    missing_result = await BackupManager().create_backup(missing_connection, job, preview())

    assert zip_result.ok
    assert zip_result.data.archive_path.endswith(".zip")
    assert "zip -qr" in zip_connection.commands[-1]
    assert not missing_result.ok
    assert "blocked" in missing_result.message


@pytest.mark.asyncio
async def test_new_target_backup_records_remove_on_rollback() -> None:
    connection = FakeConnection()
    manager = BackupManager()
    job = DeploymentJob(name="New", remote_target_folder="/var/www/new-site")

    backup_result = await manager.create_backup(connection, job, preview(target_exists=False))
    restore_result = await manager.restore_backup(connection, job, backup_result.data, run_id="run-1")

    assert backup_result.ok
    assert not backup_result.data.target_existed
    assert restore_result.ok
    assert "rm -rf -- '/var/www/new-site'" in connection.commands[-1]


@pytest.mark.asyncio
async def test_restore_uses_staging_swap_and_recovery_path() -> None:
    connection = FakeConnection()
    manager = BackupManager()
    job = DeploymentJob(name="Site", remote_target_folder="/var/www/site")
    backup = (await manager.create_backup(connection, job, preview())).data

    result = await manager.restore_backup(connection, job, backup, run_id="abc")

    assert result.ok
    command = connection.commands[-1]
    assert ".rfm-restore-abc" in command
    assert ".rfm-failed-abc" in command
    assert "mv --" in command
