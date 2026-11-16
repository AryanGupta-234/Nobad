from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class TransferProgressEvent:
    job_id: str
    source_path: str
    destination_path: str
    bytes_done: int
    bytes_total: int
    current_file: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def percent(self) -> float:
        if self.bytes_total <= 0:
            return 0.0
        return min(100.0, (self.bytes_done / self.bytes_total) * 100)


@dataclass(frozen=True, slots=True)
class TransferLogEvent:
    job_id: str
    level: str
    message: str
    technical_details: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
