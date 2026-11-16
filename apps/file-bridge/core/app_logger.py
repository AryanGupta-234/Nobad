from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from security.secret_scanner import redact_text


@dataclass(frozen=True, slots=True)
class AppLogRecord:
    operation: str
    level: str
    message: str
    technical_details: str | None = None
    profile_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def redacted(self) -> "AppLogRecord":
        return AppLogRecord(
            operation=self.operation,
            level=self.level,
            message=redact_text(self.message),
            technical_details=redact_text(self.technical_details) if self.technical_details else None,
            profile_id=self.profile_id,
            created_at=self.created_at,
        )
