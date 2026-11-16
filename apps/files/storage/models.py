from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SchemaMigrationModel(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ConnectionProfileModel(Base):
    __tablename__ = "connection_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    profile_type: Mapped[str] = mapped_column(String, nullable=False)
    protocol: Mapped[str] = mapped_column(String, nullable=False)
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    auth_type: Mapped[str] = mapped_column(String, nullable=False)
    password_secret_ref: Mapped[str | None] = mapped_column(String)
    ssh_private_key_path: Mapped[str | None] = mapped_column(String)
    ssh_private_key_passphrase_secret_ref: Mapped[str | None] = mapped_column(String)
    default_local_path: Mapped[str | None] = mapped_column(String)
    default_remote_path: Mapped[str | None] = mapped_column(String)
    environment_notes: Mapped[str | None] = mapped_column(Text)
    domain_mapping: Mapped[str | None] = mapped_column(String)
    public_url_mapping: Mapped[str | None] = mapped_column(String)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    created_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_connected_date: Mapped[datetime | None] = mapped_column(DateTime)


class SecureSecretReferenceModel(Base):
    __tablename__ = "secure_secret_references"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("connection_profiles.id"), nullable=False)
    service_name: Mapped[str] = mapped_column(String, nullable=False)
    account_name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BookmarkModel(Base):
    __tablename__ = "bookmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("connection_profiles.id"))
    label: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)


class TransferHistoryModel(Base):
    __tablename__ = "transfer_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_connection: Mapped[str | None] = mapped_column(String)
    destination_connection: Mapped[str | None] = mapped_column(String)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    destination_path: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    size: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SyncJobModel(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    destination_path: Mapped[str] = mapped_column(String, nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)


class SyncBaselineModel(Base):
    __tablename__ = "sync_baselines"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("sync_jobs.id"), nullable=False, unique=True, index=True)
    profile_id: Mapped[str | None] = mapped_column(String, index=True)
    local_root: Mapped[str] = mapped_column(String, nullable=False)
    remote_root: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SyncBaselineEntryModel(Base):
    __tablename__ = "sync_baseline_entries"
    __table_args__ = (UniqueConstraint("baseline_id", "path", name="uq_sync_baseline_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("sync_baselines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    path: Mapped[str] = mapped_column(String, nullable=False)
    local_state: Mapped[dict] = mapped_column(JSON, default=dict)
    remote_state: Mapped[dict] = mapped_column(JSON, default=dict)


class DeploymentJobModel(Base):
    __tablename__ = "deployment_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    template: Mapped[str] = mapped_column(String, nullable=False)
    local_build_folder: Mapped[str] = mapped_column(String, nullable=False)
    remote_target_folder: Mapped[str] = mapped_column(String, nullable=False)
    options: Mapped[dict] = mapped_column(JSON, default=dict)


class DeploymentRunModel(Base):
    __tablename__ = "deployment_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    profile_id: Mapped[str | None] = mapped_column(String, index=True)
    profile_name: Mapped[str] = mapped_column(String, nullable=False)
    host: Mapped[str] = mapped_column(String, nullable=False)
    remote_target: Mapped[str] = mapped_column(String, nullable=False)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False, default="deploy")
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    uploads: Mapped[int] = mapped_column(Integer, default=0)
    overwrites: Mapped[int] = mapped_column(Integer, default=0)
    deletes: Mapped[int] = mapped_column(Integer, default=0)
    bytes_total: Mapped[int] = mapped_column(Integer, default=0)
    health_ok: Mapped[bool | None] = mapped_column(Boolean)
    artifact_path: Mapped[str | None] = mapped_column(String)
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False)
    rollback_error: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, default="")
    preview_digest: Mapped[str] = mapped_column(String, default="")


class DeploymentRunStageModel(Base):
    __tablename__ = "deployment_run_stages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("deployment_runs.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    output_excerpt: Mapped[str] = mapped_column(Text, default="")


class DeploymentArtifactModel(Base):
    __tablename__ = "deployment_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    profile_id: Mapped[str | None] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    restorable: Mapped[bool] = mapped_column(Boolean, default=True)
    imported: Mapped[bool] = mapped_column(Boolean, default=False)
    artifact_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class CredentialVaultMetadataModel(Base):
    __tablename__ = "credential_vault_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    kdf_name: Mapped[str] = mapped_column(String, nullable=False)
    salt: Mapped[str] = mapped_column(String, nullable=False)
    kdf_params: Mapped[dict] = mapped_column(JSON, default=dict)
    verifier_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CredentialProjectModel(Base):
    __tablename__ = "credential_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CredentialItemModel(Base):
    __tablename__ = "credential_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("credential_projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String, default="")
    url_host: Mapped[str] = mapped_column(String, default="")
    environment_key: Mapped[str] = mapped_column(String, default="", index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CredentialCustomFieldModel(Base):
    __tablename__ = "credential_custom_fields"
    __table_args__ = (UniqueConstraint("item_id", "name", name="uq_credential_custom_field_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("credential_items.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CredentialAuditEventModel(Base):
    __tablename__ = "credential_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(String, index=True)
    item_id: Mapped[str | None] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RecentPathModel(Base):
    __tablename__ = "recent_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str | None] = mapped_column(String)
    path: Mapped[str] = mapped_column(String, nullable=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EditorSessionModel(Base):
    __tablename__ = "editor_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str | None] = mapped_column(String)
    local_temp_path: Mapped[str] = mapped_column(String, nullable=False)
    remote_path: Mapped[str | None] = mapped_column(String)
    dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppSettingModel(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)


class OperationLogModel(Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str | None] = mapped_column(String)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    technical_details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KnownHostCacheModel(Base):
    __tablename__ = "known_hosts_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CustomPlaybookSnippetModel(Base):
    __tablename__ = "custom_playbook_snippets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, default="custom")
    safety: Mapped[str] = mapped_column(String, default="safe")
    safety_label: Mapped[str] = mapped_column(String, default="Safe")
    description: Mapped[str] = mapped_column(Text, default="")
    script_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list] = mapped_column(JSON, default=list)
    steps_json: Mapped[list] = mapped_column(JSON, default=list)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlaybookExecutionHistoryModel(Base):
    __tablename__ = "playbook_execution_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    playbook_id: Mapped[str] = mapped_column(String, index=True)
    profile_id: Mapped[str | None] = mapped_column(String, index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    exit_code: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="success")
    output_summary: Mapped[str] = mapped_column(Text, default="")

