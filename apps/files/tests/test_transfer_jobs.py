from __future__ import annotations

from transfers.queue import TransferQueue
from transfers.transfer_job import TransferDirection, TransferJob, TransferStatus


def test_transfer_job_state_transitions() -> None:
    job = TransferJob(None, None, "a", "b", TransferDirection.LOCAL_TO_SERVER)
    job.mark_running()
    assert job.status == TransferStatus.RUNNING
    job.mark_completed()
    assert job.status == TransferStatus.COMPLETED
    assert job.progress == 100


def test_retry_failed_requeues_jobs() -> None:
    job = TransferJob(None, None, "a", "b", TransferDirection.LOCAL_TO_SERVER)
    job.mark_failed("boom")
    queue = TransferQueue()
    queue.add(job)

    retried = queue.retry_failed()

    assert retried == [job]
    assert job.status == TransferStatus.QUEUED
    assert job.retry_count == 1
    assert job.error_message is None

