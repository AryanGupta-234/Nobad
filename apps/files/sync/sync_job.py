from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4


class SyncMode(StrEnum):
    LOCAL_TO_REMOTE = "local_to_remote"
    REMOTE_TO_LOCAL = "remote_to_local"
    REMOTE_TO_REMOTE = "remote_to_remote"
    TWO_WAY = "two_way"


@dataclass(slots=True)
class SyncJob:
    name: str
    mode: SyncMode
    source_path: str
    destination_path: str
    ignore_patterns: list[str] = field(default_factory=list)
    profile_id: str | None = None
    checksum_policy: str = "ambiguous"
    conflict_suffix: str = "remote-conflict"
    transfer_engine: str = "queue"
    id: str = field(default_factory=lambda: str(uuid4()))
