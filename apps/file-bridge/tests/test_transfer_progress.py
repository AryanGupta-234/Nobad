from __future__ import annotations

import asyncio
from pathlib import Path

from transfers.events import TransferProgressEvent
from transfers.progress import ProgressThrottler
from transfers.transfer_job import TransferDirection, TransferJob
from transfers.transfer_manager import TransferManager


def test_transfer_progress_percent_speed_eta() -> None:
    job = TransferJob(None, None, "a", "b", TransferDirection.LOCAL_TO_SERVER)
    job.mark_running()
    job.update_progress(bytes_done=50, bytes_total=100, current_file="a")

    assert job.progress == 50
    assert job.bytes_done == 50
    assert job.bytes_total == 100
    assert job.current_file == "a"


def test_transfer_progress_event_percent() -> None:
    event = TransferProgressEvent("job", "a", "b", 25, 100)
    assert event.percent == 25


def test_progress_throttler_keeps_final_event() -> None:
    throttler = ProgressThrottler(interval_seconds=1)
    assert throttler.should_emit(now=0.1) is False
    assert throttler.should_emit(now=1.2) is True
    assert throttler.should_emit(now=1.3) is False
    assert throttler.should_emit(force=True, now=1.31) is True


class FakeRemoteOps:
    async def upload_file(self, local_path: Path, remote_path: str, *, progress_callback=None):
        from core.result import OperationResult

        if progress_callback:
            progress_callback(str(local_path), remote_path, 5, 10)
            progress_callback(str(local_path), remote_path, 10, 10)
        return OperationResult.success("uploaded")


def test_transfer_manager_upload_emits_progress(tmp_path) -> None:
    local = tmp_path / "file.txt"
    local.write_text("hello", encoding="utf-8")
    manager = TransferManager()
    seen = []

    result = asyncio.run(
        manager.upload_file(
            FakeRemoteOps(),
            local_path=local,
            remote_path="remote.txt",
            on_progress=lambda job, event: seen.append((job.progress, event.percent)),
        )
    )

    assert result.ok
    assert result.data.progress == 100
    assert seen[-1] == (100, 100)


def test_transfer_manager_throttles_progress_but_keeps_final_event() -> None:
    manager = TransferManager(progress_emit_interval=10)
    job = TransferJob(None, None, "local", "remote", TransferDirection.LOCAL_TO_SERVER)
    job.mark_running()
    emitted_progress = []
    progress_events = []
    log_messages = []
    manager.job_updated.connect(lambda updated: emitted_progress.append(updated.bytes_done))
    manager.log_event.connect(lambda event: log_messages.append(event.message))

    callback = manager._progress_callback(  # noqa: SLF001 - intentional focused regression test
        job,
        lambda _job, event: progress_events.append(event.bytes_done),
    )
    callback("local", "remote", 10, 100)
    callback("local", "remote", 20, 100)
    callback("local", "remote", 30, 100)
    callback("local", "remote", 100, 100)

    assert job.bytes_done == 100
    assert emitted_progress == [10, 100]
    assert progress_events == [10, 100]
    assert "First transfer progress received." in log_messages
    assert "Final transfer progress reached 100%." in log_messages
