from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ArchiveFormat(StrEnum):
    ZIP = "zip"
    TAR = "tar"
    TAR_GZ = "tar.gz"


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    name: str
    size: int | None = None
    is_link: bool = False


@dataclass(frozen=True, slots=True)
class ArchivePreview:
    archive_path: str
    format: ArchiveFormat
    members: list[ArchiveMember]
    safe: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def total_size(self) -> int | None:
        sizes = [member.size for member in self.members if member.size is not None]
        if len(sizes) != len(self.members):
            return None
        return sum(sizes)

    @property
    def member_names(self) -> list[str]:
        return [member.name for member in self.members]


@dataclass(frozen=True, slots=True)
class ArchiveOperationRequest:
    sources: list[str | Path]
    destination: str | Path
    archive_format: ArchiveFormat


@dataclass(frozen=True, slots=True)
class FolderSizeResult:
    path: str
    size_bytes: int
    source: str = "local"
