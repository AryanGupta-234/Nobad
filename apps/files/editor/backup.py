from __future__ import annotations

from datetime import UTC, datetime


def backup_path_for(remote_path: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{remote_path}.bak.{timestamp}"

