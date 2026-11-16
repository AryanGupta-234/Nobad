from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(frozen=True, slots=True)
class TransferProgress:
    bytes_done: int
    bytes_total: int | None = None
    speed_bytes_per_second: float | None = None

    @property
    def percent(self) -> float:
        if not self.bytes_total:
            return 0.0
        return min(100.0, (self.bytes_done / self.bytes_total) * 100)


class ProgressThrottler:
    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self._last_emit = 0.0

    def should_emit(self, *, force: bool = False, now: float | None = None) -> bool:
        if force:
            self._last_emit = now if now is not None else time.monotonic()
            return True
        current = now if now is not None else time.monotonic()
        if current - self._last_emit >= self.interval_seconds:
            self._last_emit = current
            return True
        return False
