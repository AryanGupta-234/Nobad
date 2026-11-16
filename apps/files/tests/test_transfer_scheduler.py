from __future__ import annotations

import asyncio
import stat
from dataclasses import dataclass
from pathlib import Path

from core.result import OperationResult
from file_ops.base import FileItem, FileKind
from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from transfers.transfer_job import TransferStatus
from transfers.transfer_manager import TransferManager, clamp_concurrent_transfers


@dataclass
class FakeAttrs:
    permissions: int = stat.S_IFREG | 0o644
    size: int = 5
    mtime: int = 1


class FakeRemoteOps:
    def __init__(self, *, existing: set[str] | None = None, delay: float = 0.0) -> None:
        self.files: dict[str, bytes] = {path: b"old" for path in existing or set()}
        self.folders: set[str] = set()
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def upload_file(self, local_path: Path, remote_path: str, *, progress_callback=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            data = local_path.read_bytes()
            if progress_callback:
                progress_callback(str(local_path), remote_path, len(data), len(data))
            if self.delay:
                await asyncio.sleep(self.delay)
            self.files[remote_path] = data
            return OperationResult.success("uploaded")
        finally:
            self.active -= 1

    async def download_file(self, remote_path: str, local_path: Path, *, progress_callback=None):
        data = self.files.get(remote_path, b"hello")
        if progress_callback:
            progress_callback(remote_path, str(local_path), len(data), len(data))
        Path(local_path).write_bytes(data)
        return OperationResult.success("downloaded")

    async def rename(self, source: str, destination: str):
        self.files[destination] = self.files.pop(source)
        return OperationResult.success("renamed")

    async def delete(self, remote_path: str, *, recursive: bool = False):
        self.files.pop(remote_path, None)
        return OperationResult.success("deleted")

    async def stat(self, remote_path: str):
        if remote_path not in self.files:
            return OperationResult.failure("missing")
        return OperationResult.success("exists", data=FakeAttrs())

    async def ensure_folder(self, remote_path: str):
        self.folders.add(remote_path)
        return OperationResult.success("folder exists")


def test_concurrent_transfer_clamp() -> None:
    assert clamp_concurrent_transfers(0) == 1
    assert clamp_concurrent_transfers(3) == 3
    assert clamp_concurrent_transfers(99) == 16


def test_transfer_scheduler_respects_max_concurrency(tmp_path: Path) -> None:
    async def run() -> FakeRemoteOps:
        remote = FakeRemoteOps(delay=0.01)
        manager = TransferManager(max_concurrent=2)
        for index in range(5):
            local = tmp_path / f"{index}.txt"
            local.write_text("hello", encoding="utf-8")
            manager.enqueue_upload_file(
                remote,
                local_path=local,
                remote_path=f"/remote/{index}.txt",
                conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
            )
        await manager.run_until_idle()
        return remote

    remote = asyncio.run(run())

    assert remote.max_active <= 2
    assert len([path for path in remote.files if path.startswith("/remote/")]) == 5


def test_upload_uses_part_file_then_renames(tmp_path: Path) -> None:
    async def run():
        remote = FakeRemoteOps()
        manager = TransferManager(max_concurrent=1)
        local = tmp_path / "file.txt"
        local.write_text("hello", encoding="utf-8")
        job = manager.enqueue_upload_file(
            remote,
            local_path=local,
            remote_path="/remote/file.txt",
            conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
        )
        await manager.run_until_idle()
        return remote, job

    remote, job = asyncio.run(run())

    assert job.status == TransferStatus.COMPLETED
    assert remote.files["/remote/file.txt"] == b"hello"
    assert all(".part-" not in path for path in remote.files)


def test_download_uses_part_file_then_renames(tmp_path: Path) -> None:
    async def run():
        remote = FakeRemoteOps(existing={"/remote/file.txt"})
        remote.files["/remote/file.txt"] = b"hello"
        manager = TransferManager(max_concurrent=1)
        target = tmp_path / "file.txt"
        item = FileItem("file.txt", "/remote/file.txt", FileKind.FILE, size=5)
        job = manager.enqueue_download_file(
            remote,
            remote_item=item,
            local_path=target,
            conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
        )
        await manager.run_until_idle()
        return target, job

    target, job = asyncio.run(run())

    assert job.status == TransferStatus.COMPLETED
    assert target.read_bytes() == b"hello"
    assert not list(tmp_path.glob("*.part-*"))


def test_conflict_skip_marks_job_cancelled(tmp_path: Path) -> None:
    async def run():
        remote = FakeRemoteOps(existing={"/remote/file.txt"})
        manager = TransferManager(max_concurrent=1)
        local = tmp_path / "file.txt"
        local.write_text("hello", encoding="utf-8")
        job = manager.enqueue_upload_file(
            remote,
            local_path=local,
            remote_path="/remote/file.txt",
            conflict_decision=ConflictDecision(ConflictPolicy.SKIP),
        )
        await manager.run_until_idle()
        return job

    job = asyncio.run(run())

    assert job.status == TransferStatus.CANCELLED


def test_recursive_upload_queues_files(tmp_path: Path) -> None:
    root = tmp_path / "site"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("home", encoding="utf-8")
    (root / "assets" / "app.js").write_text("js", encoding="utf-8")
    manager = TransferManager()

    jobs = manager.enqueue_upload_folder(
        FakeRemoteOps(),
        local_folder=root,
        remote_folder="/public_html",
        conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
    )

    assert [job.destination_path for job in jobs] == ["/public_html/assets/app.js", "/public_html/index.html"]


def test_cancel_batch_cancels_only_matching_queued_jobs(tmp_path: Path) -> None:
    async def run():
        remote = FakeRemoteOps()
        manager = TransferManager()
        first = tmp_path / "first.txt"
        second = tmp_path / "second.txt"
        first.write_text("one", encoding="utf-8")
        second.write_text("two", encoding="utf-8")
        matching = manager.enqueue_upload_file(
            remote,
            local_path=first,
            remote_path="/remote/first.txt",
            batch_id="deployment-1",
        )
        other = manager.enqueue_upload_file(
            remote,
            local_path=second,
            remote_path="/remote/second.txt",
            batch_id="other",
        )
        result = await manager.cancel_batch("deployment-1")
        return result, matching, other

    result, matching, other = asyncio.run(run())

    assert result.ok
    assert matching.status == TransferStatus.CANCELLED
    assert other.status == TransferStatus.QUEUED
