from __future__ import annotations

import asyncio
import stat
from dataclasses import dataclass
from pathlib import Path

from core.result import OperationResult
from sync.diff_engine import SyncAction, SyncPlanEntry, SyncPreview, SyncTargetSide
from sync.sync_executor import SyncExecutionPolicy, SyncExecutor
from sync.sync_job import SyncJob, SyncMode
from transfers.transfer_manager import TransferManager


@dataclass
class FakeAttrs:
    permissions: int = stat.S_IFREG | 0o644
    size: int = 5
    mtime: int = 1


class FakeRemoteOps:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.folders: set[str] = set()

    async def upload_file(self, local_path: Path, remote_path: str, *, progress_callback=None):
        data = Path(local_path).read_bytes()
        if progress_callback:
            progress_callback(str(local_path), remote_path, len(data), len(data))
        self.files[remote_path] = data
        return OperationResult.success("uploaded")

    async def download_file(self, remote_path: str, local_path: Path, *, progress_callback=None):
        data = self.files[remote_path]
        if progress_callback:
            progress_callback(remote_path, str(local_path), len(data), len(data))
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(data)
        return OperationResult.success("downloaded")

    async def rename(self, source: str, destination: str):
        self.files[destination] = self.files.pop(source)
        return OperationResult.success("renamed")

    async def delete(self, remote_path: str, *, recursive: bool = False):
        self.deleted.append(remote_path)
        self.files.pop(remote_path, None)
        return OperationResult.success("deleted")

    async def stat(self, remote_path: str):
        if remote_path not in self.files:
            return OperationResult.failure("missing")
        return OperationResult.success("exists", data=FakeAttrs(size=len(self.files[remote_path])))

    async def ensure_folder(self, remote_path: str):
        self.folders.add(remote_path)
        return OperationResult.success("folder exists")


def test_sync_executor_uploads_then_deletes_remote_only_files(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    local_root.mkdir()
    (local_root / "new.txt").write_text("new", encoding="utf-8")
    remote = FakeRemoteOps()
    remote.files["/site/old.txt"] = b"old"
    preview = SyncPreview(
        entries=[
            SyncPlanEntry(
                "new.txt",
                SyncAction.UPLOAD,
                "Missing from destination",
                source_size=3,
                source_side=SyncTargetSide.LOCAL,
                target_side=SyncTargetSide.REMOTE,
            ),
            SyncPlanEntry(
                "old.txt",
                SyncAction.DELETE,
                "Destination-only item will be deleted",
                destination_size=3,
                target_side=SyncTargetSide.REMOTE,
            ),
        ],
        uploads=["new.txt"],
        deletes=["old.txt"],
    )
    job = SyncJob("Upload", SyncMode.LOCAL_TO_REMOTE, str(local_root), "/site")
    manager = TransferManager(max_concurrent=1)

    result = asyncio.run(
        SyncExecutor().execute(
            job,
            preview,
            remote,
            manager,
            policy=SyncExecutionPolicy(destructive_confirmed=True),
        )
    )

    assert result.ok
    assert remote.files["/site/new.txt"] == b"new"
    assert "/site/old.txt" not in remote.files
    assert remote.deleted[-1] == "/site/old.txt"
    assert result.data.queued_transfers == 1
    assert result.data.remote_deletes == 1


def test_sync_executor_requires_confirmation_for_deletes(tmp_path: Path) -> None:
    remote = FakeRemoteOps()
    remote.files["/site/old.txt"] = b"old"
    preview = SyncPreview(
        entries=[
            SyncPlanEntry(
                "old.txt",
                SyncAction.DELETE,
                "Destination-only item will be deleted",
                target_side=SyncTargetSide.REMOTE,
            )
        ],
        deletes=["old.txt"],
    )
    job = SyncJob("Upload", SyncMode.LOCAL_TO_REMOTE, str(tmp_path), "/site")

    result = asyncio.run(SyncExecutor().execute(job, preview, remote, TransferManager()))

    assert not result.ok
    assert remote.files["/site/old.txt"] == b"old"
    assert remote.deleted == []


def test_sync_executor_downloads_and_deletes_local_only_files(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    local_root.mkdir()
    (local_root / "local-only.txt").write_text("old", encoding="utf-8")
    remote = FakeRemoteOps()
    remote.files["/site/remote.txt"] = b"remote"
    preview = SyncPreview(
        entries=[
            SyncPlanEntry(
                "remote.txt",
                SyncAction.DOWNLOAD,
                "Missing from destination",
                source_size=6,
                source_side=SyncTargetSide.REMOTE,
                target_side=SyncTargetSide.LOCAL,
            ),
            SyncPlanEntry(
                "local-only.txt",
                SyncAction.DELETE,
                "Destination-only item will be deleted",
                target_side=SyncTargetSide.LOCAL,
            ),
        ],
        downloads=["remote.txt"],
        deletes=["local-only.txt"],
    )
    job = SyncJob("Download", SyncMode.REMOTE_TO_LOCAL, "/site", str(local_root))

    result = asyncio.run(
        SyncExecutor().execute(
            job,
            preview,
            remote,
            TransferManager(max_concurrent=1),
            policy=SyncExecutionPolicy(destructive_confirmed=True),
        )
    )

    assert result.ok
    assert (local_root / "remote.txt").read_bytes() == b"remote"
    assert not (local_root / "local-only.txt").exists()
    assert result.data.local_deletes == 1


def test_sync_executor_blocks_conflicts() -> None:
    preview = SyncPreview(
        entries=[
            SyncPlanEntry(
                "config.json",
                SyncAction.CONFLICT,
                "Both sides differ",
                source_side=SyncTargetSide.LOCAL,
                target_side=SyncTargetSide.REMOTE,
            )
        ],
        conflicts=["config.json"],
    )
    job = SyncJob("Two way", SyncMode.TWO_WAY, "local", "remote")

    result = asyncio.run(SyncExecutor().execute(job, preview, FakeRemoteOps(), TransferManager()))

    assert not result.ok
    assert "conflicts" in result.message
