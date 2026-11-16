from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
import json
from uuid import uuid4

from sync.diff_engine import SyncPreview


class DeploymentMode(StrEnum):
    UPLOAD_ONLY = "upload_only"
    MIRROR = "mirror"


class DeploymentStrategy(StrEnum):
    IN_PLACE = "in_place"
    ATOMIC_RELEASE = "atomic_release"


class DeploymentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class DeploymentArtifactKind(StrEnum):
    BACKUP = "backup"
    RELEASE = "release"


class HealthCheckOrigin(StrEnum):
    DESKTOP = "desktop"
    REMOTE = "remote"


class DeploymentStage(StrEnum):
    VALIDATING = "validating"
    BUILDING = "building"
    PREVIEWING = "previewing"
    LOCKING = "locking"
    BACKING_UP = "backing_up"
    PREPARING_RELEASE = "preparing_release"
    TRANSFERRING = "transferring"
    DELETING = "deleting"
    CHMOD = "chmod"
    POST_DEPLOY = "post_deploy"
    SWITCHING_RELEASE = "switching_release"
    CACHE_CLEAR = "cache_clear"
    RESTART = "restart"
    HEALTH_CHECK = "health_check"
    ROLLING_BACK = "rolling_back"
    PRUNING_BACKUPS = "pruning_backups"
    PRUNING_RELEASES = "pruning_releases"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class HealthCheckConfig:
    command: str = ""
    http_url: str = ""
    http_origin: HealthCheckOrigin = HealthCheckOrigin.DESKTOP
    attempts: int = 3
    timeout_seconds: int = 10
    interval_seconds: int = 2
    minimum_status: int = 200
    maximum_status: int = 399
    expected_substring: str = ""
    verify_tls: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.command.strip() or self.http_url.strip())


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    ok: bool
    message: str
    command_ok: bool | None = None
    http_ok: bool | None = None
    status_code: int | None = None
    attempts_used: int = 0
    warnings: list[str] = field(default_factory=list)
    technical_details: str | None = None


@dataclass(slots=True)
class DeploymentJob:
    name: str
    template: str = "Generic Folder"
    local_build_folder: str = ""
    remote_target_folder: str = ""
    options: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    profile_id: str | None = None
    mode: DeploymentMode = DeploymentMode.UPLOAD_ONLY
    local_project_folder: str = ""
    ignore_patterns: list[str] = field(default_factory=list)
    run_local_build: bool = False
    local_build_command: str = ""
    chmod_enabled: bool = False
    chmod_mode: str = "755"
    post_deploy_command: str = ""
    cache_clear_command: str = ""
    restart_command: str = ""
    backup_directory: str = ""
    backup_retention: int = 5
    auto_rollback: bool = True
    strategy: DeploymentStrategy = DeploymentStrategy.IN_PLACE
    release_retention: int = 5
    health_check: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    stale_lock_seconds: int = 7200
    history_retention: int = 100

    def resolved_project_folder(self) -> str:
        return self.local_project_folder or self.local_build_folder


@dataclass(frozen=True, slots=True)
class DeploymentPreview:
    sync_preview: SyncPreview
    target_exists: bool
    backup_directory: str
    backup_archive_path: str
    local_root: str
    remote_root: str
    digest: str = ""

    @property
    def uploads(self) -> int:
        return len(self.sync_preview.uploads)

    @property
    def overwrites(self) -> int:
        return len(self.sync_preview.overwrites)

    @property
    def deletes(self) -> int:
        return len(self.sync_preview.deletes)

    @property
    def bytes_total(self) -> int:
        return self.sync_preview.total_size

    def calculated_digest(self) -> str:
        if self.digest:
            return self.digest
        payload = {
            "target_exists": self.target_exists,
            "local_root": self.local_root,
            "remote_root": self.remote_root,
            "entries": [
                {
                    "path": entry.path,
                    "action": entry.action.value,
                    "source_size": entry.source_size,
                    "destination_size": entry.destination_size,
                }
                for entry in self.sync_preview.entries
            ],
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeploymentExecutionPolicy:
    confirmed: bool = False
    rollback_on_failure: bool = True
    break_stale_lock: bool = False


@dataclass(frozen=True, slots=True)
class DeploymentExecutionResult:
    deployment_id: str
    batch_id: str
    uploads: int = 0
    overwrites: int = 0
    deletes: int = 0
    backup_path: str | None = None
    rolled_back: bool = False
    rollback_error: str | None = None
    cancelled: bool = False
    run_id: str | None = None
    strategy: DeploymentStrategy = DeploymentStrategy.IN_PLACE
    release_path: str | None = None
    previous_release_path: str | None = None
    health_check: HealthCheckResult | None = None
    preview_changed: bool = False


@dataclass(frozen=True, slots=True)
class DeploymentStageEvent:
    deployment_id: str
    stage: DeploymentStage
    message: str
    level: str = "info"
    run_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class DeploymentRun:
    job_id: str
    profile_id: str | None
    profile_name: str
    host: str
    remote_target: str
    strategy: DeploymentStrategy
    action: str = "deploy"
    id: str = field(default_factory=lambda: str(uuid4()))
    status: DeploymentRunStatus = DeploymentRunStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    uploads: int = 0
    overwrites: int = 0
    deletes: int = 0
    bytes_total: int = 0
    health_ok: bool | None = None
    artifact_path: str | None = None
    rolled_back: bool = False
    rollback_error: str | None = None
    message: str = ""
    preview_digest: str = ""

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return max(0.0, (self.finished_at - self.started_at).total_seconds())


@dataclass(slots=True)
class DeploymentStageRecord:
    run_id: str
    stage: DeploymentStage
    message: str
    level: str = "info"
    id: str = field(default_factory=lambda: str(uuid4()))
    sequence: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    output_excerpt: str = ""


@dataclass(slots=True)
class DeploymentArtifact:
    run_id: str | None
    job_id: str
    profile_id: str | None
    kind: DeploymentArtifactKind
    path: str
    format: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    active: bool = False
    restorable: bool = True
    imported: bool = False
    metadata: dict = field(default_factory=dict)
