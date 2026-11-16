from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay_for(self, attempt: int) -> float:
        return self.base_delay_seconds * (2 ** max(0, attempt - 1))

