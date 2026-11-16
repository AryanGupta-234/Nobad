from __future__ import annotations

from pathlib import Path

import pytest

from core.result import OperationResult
from deployment.deployment_job import DeploymentJob, DeploymentMode
from deployment.deployment_planner import DeploymentPlanner
from file_ops.base import FileItem, FileKind
from sync.diff_engine import SyncAction


class FakeRemoteOps:
    def __init__(self, items: dict[str, list[FileItem]], *, exists: bool = True) -> None:
        self.items = items
        self.exists = exists

    async def stat(self, path: str) -> OperationResult:
        if not self.exists:
            return OperationResult.failure("Not found.")
        return OperationResult.success("Found.", data=FileItem(Path(path).name, path, FileKind.DIRECTORY))

    async def list_dir(self, path: str, *, show_hidden: bool = False) -> OperationResult:
        return OperationResult.success("Listed.", data=self.items.get(path, []))


@pytest.mark.asyncio
async def test_upload_only_preserves_remote_only_files(tmp_path) -> None:
    (tmp_path / "index.html").write_text("new", encoding="utf-8")
    root = "/srv/site"
    remote = FakeRemoteOps(
        {
            root: [
                FileItem("index.html", f"{root}/index.html", FileKind.FILE, size=1),
                FileItem("remote.txt", f"{root}/remote.txt", FileKind.FILE, size=4),
            ]
        }
    )
    job = DeploymentJob(
        name="Site",
        local_build_folder=str(tmp_path),
        remote_target_folder=root,
        mode=DeploymentMode.UPLOAD_ONLY,
    )

    result = await DeploymentPlanner().build_preview(job, remote)

    assert result.ok
    preview = result.data
    assert preview.deletes == 0
    assert any(
        entry.path == "remote.txt" and entry.action == SyncAction.SKIP
        for entry in preview.sync_preview.entries
    )


@pytest.mark.asyncio
async def test_mirror_marks_remote_only_files_for_delete(tmp_path) -> None:
    (tmp_path / "index.html").write_text("new", encoding="utf-8")
    root = "/srv/site"
    remote = FakeRemoteOps(
        {
            root: [
                FileItem("index.html", f"{root}/index.html", FileKind.FILE, size=1),
                FileItem("remote.txt", f"{root}/remote.txt", FileKind.FILE, size=4),
            ]
        }
    )
    job = DeploymentJob(
        name="Site",
        local_build_folder=str(tmp_path),
        remote_target_folder=root,
        mode=DeploymentMode.MIRROR,
    )

    result = await DeploymentPlanner().build_preview(job, remote)

    assert result.ok
    assert result.data.sync_preview.deletes == ["remote.txt"]


def test_planner_rejects_protected_target_and_invalid_chmod(tmp_path) -> None:
    planner = DeploymentPlanner()
    protected = DeploymentJob(
        name="Unsafe",
        local_build_folder=str(tmp_path),
        remote_target_folder="/",
    )
    invalid_chmod = DeploymentJob(
        name="Bad mode",
        local_build_folder=str(tmp_path),
        remote_target_folder="/var/www/site",
        chmod_enabled=True,
        chmod_mode="99x",
    )

    assert not planner.validate(protected).ok
    assert not planner.validate(invalid_chmod).ok


def test_backup_override_must_be_outside_target(tmp_path) -> None:
    job = DeploymentJob(
        name="Unsafe backup",
        local_build_folder=str(tmp_path),
        remote_target_folder="/var/www/site",
        backup_directory="/var/www/site/backups",
    )

    result = DeploymentPlanner().validate(job)

    assert not result.ok
    assert "outside" in result.message


@pytest.mark.asyncio
async def test_preview_does_not_treat_permission_failure_as_missing_target(tmp_path) -> None:
    (tmp_path / "index.html").write_text("new", encoding="utf-8")

    class PermissionDeniedRemote(FakeRemoteOps):
        async def stat(self, path: str) -> OperationResult:
            return OperationResult.failure("Permission denied.", technical_details="SFTPPermissionDenied")

    job = DeploymentJob(
        name="Site",
        local_build_folder=str(tmp_path),
        remote_target_folder="/srv/site",
    )

    result = await DeploymentPlanner().build_preview(job, PermissionDeniedRemote({}))

    assert not result.ok
    assert "inspect" in result.message
