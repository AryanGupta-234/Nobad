from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath

from sync.diff_engine import SyncAction, SyncPlanEntry, SyncPreview, SyncTargetSide


class SyncConflictChoice(StrEnum):
    USE_LOCAL = "use_local"
    USE_REMOTE = "use_remote"
    KEEP_BOTH = "keep_both"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class SyncConflictDecision:
    path: str
    choice: SyncConflictChoice


@dataclass(frozen=True, slots=True)
class SyncResolutionPlan:
    preview: SyncPreview
    decisions: tuple[SyncConflictDecision, ...]


class SyncConflictResolver:
    def resolve(
        self,
        preview: SyncPreview,
        decisions: list[SyncConflictDecision],
        *,
        timestamp: datetime | None = None,
        suffix: str = "remote-conflict",
    ) -> SyncResolutionPlan:
        by_path = {decision.path: decision for decision in decisions}
        unresolved = [path for path in preview.conflicts if path not in by_path]
        if unresolved:
            raise ValueError(f"Unresolved sync conflicts: {', '.join(unresolved)}")
        resolved_entries: list[SyncPlanEntry] = []
        for entry in preview.entries:
            if entry.action != SyncAction.CONFLICT:
                resolved_entries.append(entry)
                continue
            decision = by_path[entry.path]
            resolved_entries.append(self._resolve_entry(entry, decision.choice, timestamp, suffix))
        resolved = _preview_from_entries(resolved_entries)
        return SyncResolutionPlan(resolved, tuple(decisions))

    def _resolve_entry(
        self,
        entry: SyncPlanEntry,
        choice: SyncConflictChoice,
        timestamp: datetime | None,
        suffix: str,
    ) -> SyncPlanEntry:
        if choice == SyncConflictChoice.USE_LOCAL:
            return SyncPlanEntry(
                entry.path,
                SyncAction.OVERWRITE,
                "Conflict resolved using local version",
                source_size=entry.source_size,
                destination_size=entry.destination_size,
                source_side=SyncTargetSide.LOCAL,
                target_side=SyncTargetSide.REMOTE,
            )
        if choice == SyncConflictChoice.USE_REMOTE:
            return SyncPlanEntry(
                entry.path,
                SyncAction.DOWNLOAD,
                "Conflict resolved using remote version",
                source_size=entry.destination_size,
                destination_size=entry.source_size,
                source_side=SyncTargetSide.REMOTE,
                target_side=SyncTargetSide.LOCAL,
            )
        if choice == SyncConflictChoice.SKIP:
            return SyncPlanEntry(entry.path, SyncAction.SKIP, "Conflict skipped; baseline remains unchanged")
        stamp = (timestamp or datetime.now()).strftime("%Y%m%d-%H%M%S")
        pure = PurePosixPath(entry.path)
        alternate = str(pure.with_name(f"{pure.stem}.{suffix}-{stamp}{pure.suffix}"))
        return SyncPlanEntry(
            entry.path,
            SyncAction.KEEP_BOTH,
            "Local version is canonical; remote version is preserved under a conflict name",
            source_size=entry.source_size,
            destination_size=entry.destination_size,
            source_side=SyncTargetSide.LOCAL,
            target_side=SyncTargetSide.REMOTE,
            alternate_path=alternate,
        )


def _preview_from_entries(entries: list[SyncPlanEntry]) -> SyncPreview:
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
