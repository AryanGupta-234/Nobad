from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class OperationStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class OperationResult:
    status: OperationStatus
    message: str
    technical_details: str | None = None
    warnings: list[str] = field(default_factory=list)
    affected_paths: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    retryable: bool = False
    suggested_fix: str | None = None
    data: Any = None

    @property
    def ok(self) -> bool:
        return self.status == OperationStatus.SUCCESS

    @classmethod
    def success(
        cls,
        message: str,
        *,
        data: Any = None,
        affected_paths: list[str] | None = None,
        warnings: list[str] | None = None,
        logs: list[str] | None = None,
    ) -> "OperationResult":
        return cls(
            status=OperationStatus.SUCCESS,
            message=message,
            data=data,
            affected_paths=affected_paths or [],
            warnings=warnings or [],
            logs=logs or [],
        )

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        data: Any = None,
        technical_details: str | None = None,
        warnings: list[str] | None = None,
        retryable: bool = False,
        suggested_fix: str | None = None,
        logs: list[str] | None = None,
    ) -> "OperationResult":
        return cls(
            status=OperationStatus.FAILED,
            message=message,
            data=data,
            technical_details=technical_details,
            warnings=warnings or [],
            retryable=retryable,
            suggested_fix=suggested_fix,
            logs=logs or [],
        )

    @classmethod
    def skipped(cls, message: str, *, warnings: list[str] | None = None) -> "OperationResult":
        return cls(status=OperationStatus.SKIPPED, message=message, warnings=warnings or [])


def result_from_exception(message: str, exc: BaseException, *, retryable: bool = False) -> OperationResult:
    return OperationResult.failure(
        message,
        technical_details=f"{type(exc).__name__}: {exc}",
        retryable=retryable,
    )
