from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from storage.repositories import SyncBaselineRepository
from sync.baseline import SyncBaseline, SyncBaselineEntry, state_from_manifest


class SyncBaselineService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def get(self, job_id: str) -> SyncBaseline | None:
        with self.session_factory() as session:
            return SyncBaselineRepository(session).get_for_job(job_id)

    def save(
        self,
        *,
        job,
        local_entries: list,
        remote_entries: list,
        preserve_paths: set[str] | None = None,
    ) -> SyncBaseline:  # type: ignore[no-untyped-def]
        preserve = preserve_paths or set()
        previous = self.get(job.id)
        local = {entry.path: entry for entry in local_entries}
        remote = {entry.path: entry for entry in remote_entries}
        entries: dict[str, SyncBaselineEntry] = {}
        for path in sorted(set(local) | set(remote)):
            if path in preserve:
                if previous is not None and path in previous.entries:
                    entries[path] = previous.entries[path]
                continue
            entries[path] = SyncBaselineEntry(
                path=path,
                local=state_from_manifest(local.get(path)),
                remote=state_from_manifest(remote.get(path)),
            )
        if previous is not None:
            for path in preserve:
                if path in previous.entries:
                    entries[path] = previous.entries[path]
        baseline = SyncBaseline(
            job_id=job.id,
            profile_id=job.profile_id,
            local_root=_local_root(job),
            remote_root=_remote_root(job),
            entries=entries,
        )
        with self.session_factory() as session:
            SyncBaselineRepository(session).replace(baseline)
            session.commit()
        return baseline


def _local_root(job) -> str:  # type: ignore[no-untyped-def]
    return job.destination_path if job.mode.value == "remote_to_local" else job.source_path


def _remote_root(job) -> str:  # type: ignore[no-untyped-def]
    return job.source_path if job.mode.value == "remote_to_local" else job.destination_path
