from __future__ import annotations

from datetime import datetime

from sync.diff_engine import SyncAction, SyncManifestEntry, SyncPlanEntry, SyncPreview, SyncTargetSide
from sync.baseline import SyncBaseline, SyncFileState, state_from_manifest
from sync.ignore_rules import should_ignore
from sync.sync_job import SyncJob, SyncMode


class SyncPlanner:
    def preview_from_paths(self, job: SyncJob, paths: list[str]) -> SyncPreview:
        skipped = [path for path in paths if should_ignore(path, job.ignore_patterns or None)]
        uploads = [path for path in paths if path not in skipped]
        entries = [
            SyncPlanEntry(
                path=path,
                action=SyncAction.UPLOAD,
                reason="New source item",
                source_side=SyncTargetSide.LOCAL,
                target_side=SyncTargetSide.REMOTE,
            )
            for path in uploads
        ] + [
            SyncPlanEntry(path=path, action=SyncAction.SKIP, reason="Ignored by sync filters")
            for path in skipped
        ]
        return SyncPreview(entries=entries, uploads=uploads, skipped=skipped)

    def preview_from_manifests(
        self,
        job: SyncJob,
        source_entries: list[SyncManifestEntry],
        destination_entries: list[SyncManifestEntry],
        baseline: SyncBaseline | None = None,
    ) -> SyncPreview:
        if job.mode == SyncMode.TWO_WAY and baseline is not None:
            return self._preview_two_way_with_baseline(job, source_entries, destination_entries, baseline)
        ignored = self._ignored_paths(source_entries + destination_entries, job)
        source = {entry.path: entry for entry in source_entries if entry.path not in ignored}
        destination = {entry.path: entry for entry in destination_entries if entry.path not in ignored}
        uploads: list[str] = []
        downloads: list[str] = []
        overwrites: list[str] = []
        deletes: list[str] = []
        conflicts: list[str] = []
        skipped = sorted(ignored)
        entries: list[SyncPlanEntry] = [
            SyncPlanEntry(path=path, action=SyncAction.SKIP, reason="Ignored by sync filters")
            for path in skipped
        ]
        total_size = 0

        for path in sorted(set(source) | set(destination)):
            source_entry = source.get(path)
            destination_entry = destination.get(path)
            if source_entry is None and destination_entry is not None:
                entry = self._destination_only_entry(job, destination_entry)
            elif source_entry is not None and destination_entry is None:
                entry = self._source_only_entry(job, source_entry)
            elif source_entry is not None and destination_entry is not None:
                entry = self._changed_or_skipped_entry(job, source_entry, destination_entry)
            else:
                continue

            entries.append(entry)
            if entry.action == SyncAction.UPLOAD:
                uploads.append(entry.path)
                total_size += entry.source_size or 0
            elif entry.action == SyncAction.DOWNLOAD:
                downloads.append(entry.path)
                total_size += entry.source_size or entry.destination_size or 0
            elif entry.action == SyncAction.OVERWRITE:
                overwrites.append(entry.path)
                total_size += entry.source_size or 0
            elif entry.action == SyncAction.DELETE:
                deletes.append(entry.path)
            elif entry.action == SyncAction.CONFLICT:
                conflicts.append(entry.path)
            elif entry.action == SyncAction.SKIP:
                skipped.append(entry.path)

        return SyncPreview(
            entries=entries,
            uploads=uploads,
            downloads=downloads,
            deletes=deletes,
            overwrites=overwrites,
            conflicts=conflicts,
            skipped=skipped,
            total_size=total_size,
        )

    def _preview_two_way_with_baseline(
        self,
        job: SyncJob,
        local_entries: list[SyncManifestEntry],
        remote_entries: list[SyncManifestEntry],
        baseline: SyncBaseline,
    ) -> SyncPreview:
        ignored = self._ignored_paths(local_entries + remote_entries, job)
        local = {entry.path: entry for entry in local_entries if entry.path not in ignored}
        remote = {entry.path: entry for entry in remote_entries if entry.path not in ignored}
        entries: list[SyncPlanEntry] = [
            SyncPlanEntry(path=path, action=SyncAction.SKIP, reason="Ignored by sync filters")
            for path in sorted(ignored)
        ]
        all_paths = sorted(set(local) | set(remote) | set(baseline.entries))
        for path in all_paths:
            if path in ignored:
                continue
            base_entry = baseline.entries.get(path)
            if base_entry is None:
                entries.append(self._new_two_way_entry(path, local.get(path), remote.get(path)))
                continue
            local_state = state_from_manifest(local.get(path))
            remote_state = state_from_manifest(remote.get(path))
            local_changed = not local_state.equivalent(base_entry.local)
            remote_changed = not remote_state.equivalent(base_entry.remote)
            entries.append(
                self._baseline_entry(
                    path,
                    local.get(path),
                    remote.get(path),
                    local_state,
                    remote_state,
                    local_changed,
                    remote_changed,
                )
            )
        return self._preview_from_entries(entries)

    def _new_two_way_entry(
        self,
        path: str,
        local: SyncManifestEntry | None,
        remote: SyncManifestEntry | None,
    ) -> SyncPlanEntry:
        if local is not None and remote is None:
            return SyncPlanEntry(
                path,
                SyncAction.UPLOAD,
                "New local file",
                source_size=local.size,
                source_side=SyncTargetSide.LOCAL,
                target_side=SyncTargetSide.REMOTE,
            )
        if remote is not None and local is None:
            return SyncPlanEntry(
                path,
                SyncAction.DOWNLOAD,
                "New remote file",
                source_size=remote.size,
                source_side=SyncTargetSide.REMOTE,
                target_side=SyncTargetSide.LOCAL,
            )
        assert local is not None and remote is not None
        if self._same_file(local, remote):
            return SyncPlanEntry(path, SyncAction.SKIP, "New file is identical on both sides")
        return self._conflict(path, local, remote, "Same new path differs on both sides")

    def _baseline_entry(
        self,
        path: str,
        local: SyncManifestEntry | None,
        remote: SyncManifestEntry | None,
        local_state: SyncFileState,
        remote_state: SyncFileState,
        local_changed: bool,
        remote_changed: bool,
    ) -> SyncPlanEntry:
        if not local_changed and not remote_changed:
            return SyncPlanEntry(path, SyncAction.SKIP, "Unchanged since last successful sync")
        if local_changed and remote_changed:
            if local_state.equivalent(remote_state):
                return SyncPlanEntry(path, SyncAction.SKIP, "Both sides changed to identical content")
            return self._conflict(path, local, remote, "Both sides changed since last successful sync")
        if local_changed:
            if local is None:
                return SyncPlanEntry(
                    path,
                    SyncAction.DELETE,
                    "Deleted locally; remote side is unchanged",
                    destination_size=remote.size if remote else None,
                    target_side=SyncTargetSide.REMOTE,
                )
            return SyncPlanEntry(
                path,
                SyncAction.OVERWRITE if remote is not None else SyncAction.UPLOAD,
                "Local side changed; remote side is unchanged",
                source_size=local.size,
                destination_size=remote.size if remote else None,
                source_side=SyncTargetSide.LOCAL,
                target_side=SyncTargetSide.REMOTE,
            )
        if remote is None:
            return SyncPlanEntry(
                path,
                SyncAction.DELETE,
                "Deleted remotely; local side is unchanged",
                destination_size=local.size if local else None,
                target_side=SyncTargetSide.LOCAL,
            )
        return SyncPlanEntry(
            path,
            SyncAction.DOWNLOAD,
            "Remote side changed; local side is unchanged",
            source_size=remote.size,
            destination_size=local.size if local else None,
            source_side=SyncTargetSide.REMOTE,
            target_side=SyncTargetSide.LOCAL,
        )

    def _conflict(
        self,
        path: str,
        local: SyncManifestEntry | None,
        remote: SyncManifestEntry | None,
        reason: str,
    ) -> SyncPlanEntry:
        return SyncPlanEntry(
            path,
            SyncAction.CONFLICT,
            reason,
            source_size=local.size if local else None,
            destination_size=remote.size if remote else None,
            source_side=SyncTargetSide.LOCAL,
            target_side=SyncTargetSide.REMOTE,
        )

    def _preview_from_entries(self, entries: list[SyncPlanEntry]) -> SyncPreview:
        return SyncPreview(
            entries=entries,
            uploads=[entry.path for entry in entries if entry.action == SyncAction.UPLOAD],
            downloads=[entry.path for entry in entries if entry.action == SyncAction.DOWNLOAD],
            deletes=[entry.path for entry in entries if entry.action == SyncAction.DELETE],
            overwrites=[entry.path for entry in entries if entry.action in {SyncAction.OVERWRITE, SyncAction.KEEP_BOTH}],
            conflicts=[entry.path for entry in entries if entry.action == SyncAction.CONFLICT],
            skipped=[entry.path for entry in entries if entry.action == SyncAction.SKIP],
            total_size=sum(
                entry.source_size or entry.destination_size or 0
                for entry in entries
                if entry.action not in {SyncAction.SKIP, SyncAction.DELETE, SyncAction.CONFLICT}
            ),
        )

    def _source_only_entry(self, job: SyncJob, entry: SyncManifestEntry) -> SyncPlanEntry:
        if job.mode == SyncMode.REMOTE_TO_LOCAL:
            return SyncPlanEntry(
                entry.path,
                SyncAction.DOWNLOAD,
                "Missing from destination",
                source_size=entry.size,
                source_side=SyncTargetSide.REMOTE,
                target_side=SyncTargetSide.LOCAL,
            )
        return SyncPlanEntry(
            entry.path,
            SyncAction.UPLOAD,
            "Missing from destination",
            source_size=entry.size,
            source_side=SyncTargetSide.LOCAL,
            target_side=SyncTargetSide.REMOTE,
        )

    def _destination_only_entry(self, job: SyncJob, entry: SyncManifestEntry) -> SyncPlanEntry:
        if job.mode == SyncMode.TWO_WAY:
            return SyncPlanEntry(
                entry.path,
                SyncAction.DOWNLOAD,
                "Missing from source",
                destination_size=entry.size,
                source_side=SyncTargetSide.REMOTE,
                target_side=SyncTargetSide.LOCAL,
            )
        target_side = SyncTargetSide.LOCAL if job.mode == SyncMode.REMOTE_TO_LOCAL else SyncTargetSide.REMOTE
        return SyncPlanEntry(
            entry.path,
            SyncAction.DELETE,
            "Destination-only item will be deleted",
            destination_size=entry.size,
            target_side=target_side,
        )

    def _changed_or_skipped_entry(
        self,
        job: SyncJob,
        source: SyncManifestEntry,
        destination: SyncManifestEntry,
    ) -> SyncPlanEntry:
        if self._same_file(source, destination):
            return SyncPlanEntry(
                source.path,
                SyncAction.SKIP,
                "Already in sync",
                source_size=source.size,
                destination_size=destination.size,
            )
        if job.mode == SyncMode.TWO_WAY:
            return SyncPlanEntry(
                source.path,
                SyncAction.CONFLICT,
                "Both sides differ; execution requires a conflict policy",
                source_size=source.size,
                destination_size=destination.size,
                source_side=SyncTargetSide.LOCAL,
                target_side=SyncTargetSide.REMOTE,
            )
        source_side = SyncTargetSide.REMOTE if job.mode == SyncMode.REMOTE_TO_LOCAL else SyncTargetSide.LOCAL
        target_side = SyncTargetSide.LOCAL if job.mode == SyncMode.REMOTE_TO_LOCAL else SyncTargetSide.REMOTE
        action = SyncAction.DOWNLOAD if job.mode == SyncMode.REMOTE_TO_LOCAL else SyncAction.OVERWRITE
        return SyncPlanEntry(
            source.path,
            action,
            "Destination differs",
            source_size=source.size,
            destination_size=destination.size,
            source_side=source_side,
            target_side=target_side,
        )

    def _same_file(self, source: SyncManifestEntry, destination: SyncManifestEntry) -> bool:
        if source.is_dir or destination.is_dir:
            return source.is_dir == destination.is_dir
        if source.size != destination.size:
            return False
        if source.checksum and destination.checksum:
            return source.checksum == destination.checksum
        return self._close_mtime(source.modified_at, destination.modified_at)

    def _close_mtime(self, source: datetime | None, destination: datetime | None) -> bool:
        if source is None or destination is None:
            return True
        return abs((source - destination).total_seconds()) <= 1

    def _ignored_paths(self, entries: list[SyncManifestEntry], job: SyncJob) -> set[str]:
        return {
            entry.path
            for entry in entries
            if should_ignore(entry.path, job.ignore_patterns or None)
        }
