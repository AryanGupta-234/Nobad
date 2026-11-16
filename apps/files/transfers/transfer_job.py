from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from file_ops.conflict_policy import ConflictPolicy


class TransferDirection(StrEnum):
    LOCAL_TO_SERVER = "local_to_server"
    SERVER_TO_LOCAL = "server_to_local"
    SERVER_TO_SERVER = "server_to_server"
    LOCAL_TO_CLOUD = "local_to_cloud"
    CLOUD_TO_LOCAL = "cloud_to_local"
    SERVER_TO_CLOUD = "server_to_cloud"
    CLOUD_TO_SERVER = "cloud_to_server"


class TransferStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class TransferJob:
    source_connection: str | None
    destination_connection: str | None
    source_path: str
    destination_path: str
    direction: TransferDirection
    size: int | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    progress: float = 0.0
    bytes_done: int = 0
    bytes_total: int | None = None
    speed: float | None = None
    eta_seconds: float | None = None
    status: TransferStatus = TransferStatus.QUEUED
    current_file: str | None = None
    retry_count: int = 0
    error_message: str | None = None
    logs: list[str] = field(default_factory=list)
    batch_id: str | None = None
    temp_path: str | None = None
    conflict_policy: ConflictPolicy | None = None
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    updated_at: datetime | None = None

    def mark_queued(self) -> None:
        self.status = TransferStatus.QUEUED
        self.error_message = None
        self.cancel_requested = False
        self.updated_at = datetime.now(UTC)

    def mark_running(self) -> None:
        self.status = TransferStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self.updated_at = self.started_at
        self.logs.append("Transfer started.")

    def mark_completed(self) -> None:
        self.progress = 100.0
        if self.bytes_total is not None:
            self.bytes_done = self.bytes_total
        self.status = TransferStatus.COMPLETED
        self.updated_at = datetime.now(UTC)
        self.logs.append("Transfer completed.")

    def mark_failed(self, message: str) -> None:
        self.status = TransferStatus.FAILED
        self.error_message = message
        self.logs.append(message)
        self.updated_at = datetime.now(UTC)

    def mark_cancelled(self, message: str = "Transfer cancelled.") -> None:
        self.status = TransferStatus.CANCELLED
        self.cancel_requested = True
        self.error_message = message
        self.logs.append(message)
        self.updated_at = datetime.now(UTC)

    def update_progress(
        self,
        *,
        bytes_done: int,
        bytes_total: int,
        current_file: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        self.bytes_done = bytes_done
        self.bytes_total = bytes_total
        self.size = bytes_total
        self.current_file = current_file
        self.progress = 0.0 if bytes_total <= 0 else min(100.0, (bytes_done / bytes_total) * 100)
        if self.started_at:
            elapsed = max(0.001, (now - self.started_at).total_seconds())
            self.speed = bytes_done / elapsed
            remaining = max(0, bytes_total - bytes_done)
            self.eta_seconds = remaining / self.speed if self.speed else None
        self.updated_at = now
