from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class SyncFileState:
    exists: bool = False
    size: int | None = None
    modified_at: datetime | None = None
    checksum: str | None = None
    is_dir: bool = False

    def equivalent(self, other: "SyncFileState") -> bool:
        if self.exists != other.exists or self.is_dir != other.is_dir:
            return False
        if not self.exists:
            return True
        if self.checksum and other.checksum:
            return self.checksum == other.checksum
        if self.size != other.size:
            return False
        if self.modified_at is None or other.modified_at is None:
            return True
        return abs((self.modified_at - other.modified_at).total_seconds()) <= 1

    def to_dict(self) -> dict:
        return {
            "exists": self.exists,
            "size": self.size,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "checksum": self.checksum,
            "is_dir": self.is_dir,
        }

    @classmethod
    def from_dict(cls, value: dict | None) -> "SyncFileState":
        data = value or {}
        modified = data.get("modified_at")
        return cls(
            exists=bool(data.get("exists", False)),
            size=data.get("size"),
            modified_at=datetime.fromisoformat(modified) if modified else None,
            checksum=data.get("checksum"),
            is_dir=bool(data.get("is_dir", False)),
        )


@dataclass(frozen=True, slots=True)
class SyncBaselineEntry:
    path: str
    local: SyncFileState = field(default_factory=SyncFileState)
    remote: SyncFileState = field(default_factory=SyncFileState)


@dataclass(slots=True)
class SyncBaseline:
    job_id: str
    local_root: str
    remote_root: str
    entries: dict[str, SyncBaselineEntry]
    profile_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def state_from_manifest(entry) -> SyncFileState:  # type: ignore[no-untyped-def]
    if entry is None:
        return SyncFileState()
    return SyncFileState(
        exists=getattr(entry, "exists", True),
        size=entry.size,
        modified_at=entry.modified_at,
        checksum=getattr(entry, "checksum", None),
        is_dir=entry.is_dir,
    )
