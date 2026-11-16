from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4


@dataclass(slots=True)
class EditorSession:
    local_path: Path
    remote_path: str | None = None
    profile_id: str | None = None
    remote_modified_at: datetime | None = None
    encoding: str = "utf-8"
    readonly: bool = False
    dirty: bool = False
    backup_enabled: bool = True
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def display_name(self) -> str:
        return self.remote_path or str(self.local_path)

