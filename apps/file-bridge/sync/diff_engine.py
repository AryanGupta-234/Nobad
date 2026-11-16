from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SyncAction(StrEnum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    OVERWRITE = "overwrite"
    DELETE = "delete"
    SKIP = "skip"
    CONFLICT = "conflict"
    KEEP_BOTH = "keep_both"


class SyncTargetSide(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class SyncManifestEntry:
    path: str
    size: int | None = None
    modified_at: datetime | None = None
    is_dir: bool = False
    checksum: str | None = None
    exists: bool = True


@dataclass(frozen=True, slots=True)
class SyncPlanEntry:
    path: str
    action: SyncAction
    reason: str
    source_size: int | None = None
    destination_size: int | None = None
    source_side: SyncTargetSide | None = None
    target_side: SyncTargetSide | None = None
    alternate_path: str | None = None


@dataclass(frozen=True, slots=True)
class SyncPreview:
    entries: list[SyncPlanEntry] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    overwrites: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total_size: int = 0
