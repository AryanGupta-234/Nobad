"""Typed execution lifecycle and result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class StepExecutionResult:
    step_id: str
    status: StepStatus
    started_at: str
    finished_at: str
    output: Any = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    task_id: str
    status: TaskStatus
    started_at: str
    finished_at: str
    steps: tuple[StepExecutionResult, ...] = ()
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def utc_now() -> str:
    """Return an offset-aware UTC timestamp."""
    return datetime.now(UTC).isoformat()
