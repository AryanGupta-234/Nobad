from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConflictPolicy(StrEnum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"
    KEEP_NEWER = "keep_newer"
    KEEP_LARGER = "keep_larger"
    COMPARE_CHECKSUM = "compare_checksum"
    ASK_EVERY_TIME = "ask_every_time"


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    policy: ConflictPolicy
    apply_to_all: bool = False
    alternate_name: str | None = None

