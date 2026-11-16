from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from transfers.transfer_job import TransferJob, TransferStatus


@dataclass
class TransferQueue:
    jobs: deque[TransferJob] = field(default_factory=deque)

    def add(self, job: TransferJob) -> None:
        self.jobs.append(job)

    def get(self, job_id: str) -> TransferJob | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    def queued(self) -> list[TransferJob]:
        return [job for job in self.jobs if job.status == TransferStatus.QUEUED]

    def running(self) -> list[TransferJob]:
        return [job for job in self.jobs if job.status == TransferStatus.RUNNING]

    def retry_failed(self) -> list[TransferJob]:
        failed = [job for job in self.jobs if job.status == TransferStatus.FAILED]
        for job in failed:
            job.retry_count += 1
            job.mark_queued()
        return failed

    def retry_job(self, job_id: str) -> TransferJob | None:
        job = self.get(job_id)
        if job is None or job.status not in {TransferStatus.FAILED, TransferStatus.CANCELLED}:
            return None
        job.retry_count += 1
        job.mark_queued()
        return job

    def clear_completed(self) -> None:
        self.jobs = deque(job for job in self.jobs if job.status != TransferStatus.COMPLETED)

    def clear_failed(self) -> None:
        self.jobs = deque(job for job in self.jobs if job.status != TransferStatus.FAILED)

    def clear_cancelled(self) -> None:
        self.jobs = deque(job for job in self.jobs if job.status != TransferStatus.CANCELLED)
