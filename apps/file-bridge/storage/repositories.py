from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.app_logger import AppLogRecord
from core.connections.profile import AuthType, ConnectionProfile, ProfileType, ProtocolType
from core.playbooks_models import (
    PlaybookExecutionRecord,
    PlaybookRecipe,
    PlaybookVariable,
)
from credentials.models import (
    CredentialAuditEvent,
    CredentialCustomField,
    CredentialItem,
    CredentialKind,
    CredentialProject,
)
from security.credential_store import SecretKind, SecureSecretReference
from security.secret_scanner import redact_text
from storage.models import (
    AppSettingModel,
    ConnectionProfileModel,
    CredentialAuditEventModel,
    CredentialCustomFieldModel,
    CredentialItemModel,
    CredentialProjectModel,
    CredentialVaultMetadataModel,
    CustomPlaybookSnippetModel,
    DeploymentArtifactModel,
    DeploymentJobModel,
    DeploymentRunModel,
    DeploymentRunStageModel,
    KnownHostCacheModel,
    OperationLogModel,
    PlaybookExecutionHistoryModel,
    RecentPathModel,
    SecureSecretReferenceModel,
    SyncBaselineEntryModel,
    SyncBaselineModel,
    SyncJobModel,
    TransferHistoryModel,
)
from deployment.deployment_job import (
    DeploymentArtifact,
    DeploymentArtifactKind,
    DeploymentJob,
    DeploymentMode,
    DeploymentRun,
    DeploymentRunStatus,
    DeploymentStage,
    DeploymentStageRecord,
    DeploymentStrategy,
    HealthCheckConfig,
    HealthCheckOrigin,
)
from sync.sync_job import SyncJob, SyncMode
from sync.baseline import SyncBaseline, SyncBaselineEntry, SyncFileState
from transfers.transfer_job import TransferJob


class ConnectionProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, profile: ConnectionProfile) -> None:
        model = ConnectionProfileModel(
            id=profile.id,
            name=profile.name,
            profile_type=profile.profile_type.value,
            protocol=profile.protocol.value,
            host=profile.host,
            port=profile.port,
            username=profile.username,
            auth_type=profile.auth_type.value,
            password_secret_ref=profile.password_secret_ref,
            ssh_private_key_path=profile.ssh_private_key_path,
            ssh_private_key_passphrase_secret_ref=profile.ssh_private_key_passphrase_secret_ref,
            default_local_path=profile.default_local_path,
            default_remote_path=profile.default_remote_path,
            environment_notes=profile.environment_notes,
            domain_mapping=profile.domain_mapping,
            public_url_mapping=profile.public_url_mapping,
            options=dict(profile.options),
            created_date=profile.created_date,
            last_connected_date=profile.last_connected_date,
        )
        self.session.merge(model)

    def get(self, profile_id: str) -> ConnectionProfile | None:
        row = self.session.get(ConnectionProfileModel, profile_id)
        return self._to_profile(row) if row else None

    def list(self) -> list[ConnectionProfile]:
        rows = self.session.query(ConnectionProfileModel).order_by(ConnectionProfileModel.name).all()
        return [self._to_profile(row) for row in rows]

    def delete(self, profile_id: str) -> None:
        row = self.session.get(ConnectionProfileModel, profile_id)
        if row:
            self.session.delete(row)

    def rename(self, profile_id: str, name: str) -> bool:
        row = self.session.get(ConnectionProfileModel, profile_id)
        if row is None:
            return False
        row.name = name
        return True

    def _to_profile(self, row: ConnectionProfileModel) -> ConnectionProfile:
        return ConnectionProfile(
            id=row.id,
            name=row.name,
            profile_type=ProfileType(row.profile_type),
            protocol=ProtocolType(row.protocol),
            host=row.host,
            port=row.port,
            username=row.username,
            auth_type=AuthType(row.auth_type),
            password_secret_ref=row.password_secret_ref,
            ssh_private_key_path=row.ssh_private_key_path,
            ssh_private_key_passphrase_secret_ref=row.ssh_private_key_passphrase_secret_ref,
            default_local_path=row.default_local_path,
            default_remote_path=row.default_remote_path,
            environment_notes=row.environment_notes,
            domain_mapping=row.domain_mapping,
            public_url_mapping=row.public_url_mapping,
            options=dict(row.options or {}),
            created_date=row.created_date,
            last_connected_date=row.last_connected_date,
        )


class SecretReferenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, profile_id: str, reference: SecureSecretReference) -> None:
        self.session.merge(
            SecureSecretReferenceModel(
                id=reference.id,
                profile_id=profile_id,
                service_name=reference.service_name,
                account_name=reference.account_name,
                kind=reference.kind.value,
            )
        )

    def get(self, reference_id: str) -> SecureSecretReference | None:
        row = self.session.get(SecureSecretReferenceModel, reference_id)
        return self._to_reference(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[SecureSecretReference]:
        rows = self.session.query(SecureSecretReferenceModel).filter_by(profile_id=profile_id).all()
        return [self._to_reference(row) for row in rows]

    def delete(self, reference_id: str) -> None:
        row = self.session.get(SecureSecretReferenceModel, reference_id)
        if row is not None:
            self.session.delete(row)

    def _to_reference(self, row: SecureSecretReferenceModel) -> SecureSecretReference:
        return SecureSecretReference(
            id=row.id,
            service_name=row.service_name,
            account_name=row.account_name,
            kind=SecretKind(row.kind),
        )


class KnownHostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def trust(self, host: str, port: int, fingerprint_sha256: str) -> None:
        row = (
            self.session.query(KnownHostCacheModel)
            .filter_by(host=host, port=port)
            .order_by(KnownHostCacheModel.id.desc())
            .first()
        )
        if row is None:
            self.session.add(
                KnownHostCacheModel(
                    host=host,
                    port=port,
                    fingerprint_sha256=fingerprint_sha256,
                )
            )
            return
        row.fingerprint_sha256 = fingerprint_sha256
        row.last_seen = datetime.now(UTC)

    def get_fingerprint(self, host: str, port: int) -> str | None:
        row = (
            self.session.query(KnownHostCacheModel)
            .filter_by(host=host, port=port)
            .order_by(KnownHostCacheModel.id.desc())
            .first()
        )
        return row.fingerprint_sha256 if row else None


class AppSettingsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str, default: dict | None = None) -> dict | None:
        row = self.session.get(AppSettingModel, key)
        return row.value if row else default

    def set(self, key: str, value: dict) -> None:
        self.session.merge(AppSettingModel(key=key, value=value))


class OperationLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: AppLogRecord) -> None:
        redacted = record.redacted()
        self.session.add(
            OperationLogModel(
                profile_id=redacted.profile_id,
                operation=redacted.operation,
                level=redacted.level,
                message=redacted.message,
                technical_details=redacted.technical_details,
                created_at=redacted.created_at,
            )
        )


class CredentialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_vault_metadata(self) -> dict | None:
        row = self.session.get(CredentialVaultMetadataModel, 1)
        if row is None:
            return None
        return {
            "id": row.id,
            "kdf_name": row.kdf_name,
            "salt": row.salt,
            "kdf_params": dict(row.kdf_params or {}),
            "verifier_payload": row.verifier_payload,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def set_vault_metadata(
        self,
        *,
        kdf_name: str,
        salt: str,
        kdf_params: dict,
        verifier_payload: str,
    ) -> None:
        self.session.merge(
            CredentialVaultMetadataModel(
                id=1,
                kdf_name=kdf_name,
                salt=salt,
                kdf_params=dict(kdf_params),
                verifier_payload=verifier_payload,
                updated_at=datetime.now(UTC),
            )
        )

    def add_project(self, project: CredentialProject) -> None:
        self.session.merge(
            CredentialProjectModel(
                id=project.id,
                name=project.name,
                description=project.description,
                tags=list(project.tags),
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )

    def get_project(self, project_id: str) -> CredentialProject | None:
        row = self.session.get(CredentialProjectModel, project_id)
        return self._to_project(row) if row else None

    def list_projects(self) -> list[CredentialProject]:
        rows = self.session.query(CredentialProjectModel).order_by(CredentialProjectModel.name).all()
        return [self._to_project(row) for row in rows]

    def delete_project(self, project_id: str) -> None:
        self.session.query(CredentialAuditEventModel).filter_by(project_id=project_id).delete()
        item_ids = [
            row.id
            for row in self.session.query(CredentialItemModel.id).filter_by(project_id=project_id).all()
        ]
        if item_ids:
            self.session.query(CredentialCustomFieldModel).filter(
                CredentialCustomFieldModel.item_id.in_(item_ids)
            ).delete(synchronize_session=False)
            self.session.query(CredentialItemModel).filter(
                CredentialItemModel.id.in_(item_ids)
            ).delete(synchronize_session=False)
        row = self.session.get(CredentialProjectModel, project_id)
        if row is not None:
            self.session.delete(row)

    def add_item(self, item: CredentialItem, *, encrypted_value: str, encrypted_notes: str = "") -> None:
        self.session.merge(
            CredentialItemModel(
                id=item.id,
                project_id=item.project_id,
                title=item.title,
                kind=item.kind.value,
                username=item.username,
                url_host=item.url_host,
                environment_key=item.environment_key,
                tags=list(item.tags),
                favorite=item.favorite,
                encrypted_value=encrypted_value,
                encrypted_notes=encrypted_notes,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )

    def get_item(self, item_id: str) -> CredentialItem | None:
        row = self.session.get(CredentialItemModel, item_id)
        return self._to_item(row) if row else None

    def get_item_encrypted(self, item_id: str) -> tuple[CredentialItem, str, str] | None:
        row = self.session.get(CredentialItemModel, item_id)
        if row is None:
            return None
        return self._to_item(row), row.encrypted_value, row.encrypted_notes or ""

    def list_items(self, project_id: str | None = None) -> list[CredentialItem]:
        query = self.session.query(CredentialItemModel)
        if project_id:
            query = query.filter_by(project_id=project_id)
        rows = query.order_by(CredentialItemModel.favorite.desc(), CredentialItemModel.title).all()
        return [self._to_item(row) for row in rows]

    def search_items(self, query_text: str, *, project_id: str | None = None) -> list[CredentialItem]:
        needle = query_text.strip().lower()
        items = self.list_items(project_id)
        if not needle:
            return items
        matches: list[CredentialItem] = []
        for item in items:
            haystack = " ".join(
                [
                    item.title,
                    item.kind.value,
                    item.username,
                    item.url_host,
                    item.environment_key,
                    " ".join(item.tags),
                ]
            ).lower()
            if needle in haystack:
                matches.append(item)
        return matches

    def delete_item(self, item_id: str) -> None:
        self.session.query(CredentialCustomFieldModel).filter_by(item_id=item_id).delete()
        self.session.query(CredentialAuditEventModel).filter_by(item_id=item_id).delete()
        row = self.session.get(CredentialItemModel, item_id)
        if row is not None:
            self.session.delete(row)

    def replace_custom_fields(
        self,
        item_id: str,
        fields: list[tuple[CredentialCustomField, str]],
    ) -> None:
        self.session.query(CredentialCustomFieldModel).filter_by(item_id=item_id).delete()
        for field, encrypted_value in fields:
            self.session.add(
                CredentialCustomFieldModel(
                    id=field.id,
                    item_id=item_id,
                    name=field.name,
                    encrypted_value=encrypted_value,
                    is_secret=field.is_secret,
                    created_at=field.created_at,
                )
            )

    def list_custom_fields(self, item_id: str) -> list[CredentialCustomField]:
        rows = (
            self.session.query(CredentialCustomFieldModel)
            .filter_by(item_id=item_id)
            .order_by(CredentialCustomFieldModel.name)
            .all()
        )
        return [self._to_custom_field(row) for row in rows]

    def list_custom_fields_encrypted(self, item_id: str) -> list[tuple[CredentialCustomField, str]]:
        rows = (
            self.session.query(CredentialCustomFieldModel)
            .filter_by(item_id=item_id)
            .order_by(CredentialCustomFieldModel.name)
            .all()
        )
        return [(self._to_custom_field(row), row.encrypted_value) for row in rows]

    def _to_project(self, row: CredentialProjectModel) -> CredentialProject:
        return CredentialProject(
            id=row.id,
            name=row.name,
            description=row.description or "",
            tags=list(row.tags or []),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _to_item(self, row: CredentialItemModel) -> CredentialItem:
        return CredentialItem(
            id=row.id,
            project_id=row.project_id,
            title=row.title,
            kind=CredentialKind(row.kind),
            username=row.username or "",
            url_host=row.url_host or "",
            environment_key=row.environment_key or "",
            tags=list(row.tags or []),
            favorite=bool(row.favorite),
            has_secret=bool(row.encrypted_value),
            has_notes=bool(row.encrypted_notes),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _to_custom_field(self, row: CredentialCustomFieldModel) -> CredentialCustomField:
        return CredentialCustomField(
            id=row.id,
            item_id=row.item_id,
            name=row.name,
            is_secret=bool(row.is_secret),
            created_at=row.created_at,
        )


class CredentialAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: CredentialAuditEvent) -> None:
        self.session.add(
            CredentialAuditEventModel(
                project_id=event.project_id,
                item_id=event.item_id,
                action=event.action,
                message=redact_text(event.message),
                created_at=event.created_at,
            )
        )

    def list(self, *, project_id: str | None = None, limit: int = 200) -> list[CredentialAuditEvent]:
        query = self.session.query(CredentialAuditEventModel)
        if project_id:
            query = query.filter_by(project_id=project_id)
        rows = query.order_by(CredentialAuditEventModel.created_at.desc()).limit(max(1, int(limit))).all()
        return [
            CredentialAuditEvent(
                id=row.id,
                project_id=row.project_id,
                item_id=row.item_id,
                action=row.action,
                message=row.message,
                created_at=row.created_at,
            )
            for row in rows
        ]


class TransferHistoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: TransferJob) -> None:
        self.session.merge(
            TransferHistoryModel(
                id=job.id,
                source_connection=job.source_connection,
                destination_connection=job.destination_connection,
                source_path=job.source_path,
                destination_path=job.destination_path,
                direction=job.direction.value,
                size=job.size,
                status=job.status.value,
                error_message=job.error_message,
                created_at=job.created_at,
            )
        )


class RecentPathRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, path: str, *, profile_id: str | None = None, is_remote: bool = False) -> None:
        self.session.add(RecentPathModel(profile_id=profile_id, path=path, is_remote=is_remote))


class SyncJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: SyncJob) -> None:
        self.session.merge(
            SyncJobModel(
                id=job.id,
                name=job.name,
                mode=job.mode.value,
                source_path=job.source_path,
                destination_path=job.destination_path,
                # Extended settings remain in JSON so existing databases stay compatible.
                filters={
                    "ignore_patterns": job.ignore_patterns,
                    "profile_id": job.profile_id,
                    "checksum_policy": job.checksum_policy,
                    "conflict_suffix": job.conflict_suffix,
                    "transfer_engine": job.transfer_engine,
                },
            )
        )

    def list(self) -> list[SyncJob]:
        rows = self.session.query(SyncJobModel).order_by(SyncJobModel.name).all()
        return [self._to_job(row) for row in rows]

    def delete(self, job_id: str) -> None:
        row = self.session.get(SyncJobModel, job_id)
        if row is not None:
            self.session.delete(row)

    def _to_job(self, row: SyncJobModel) -> SyncJob:
        filters = row.filters or {}
        return SyncJob(
            id=row.id,
            name=row.name,
            mode=SyncMode(row.mode),
            source_path=row.source_path,
            destination_path=row.destination_path,
            ignore_patterns=list(filters.get("ignore_patterns") or []),
            profile_id=filters.get("profile_id"),
            checksum_policy=str(filters.get("checksum_policy") or "ambiguous"),
            conflict_suffix=str(filters.get("conflict_suffix") or "remote-conflict"),
            transfer_engine=str(filters.get("transfer_engine") or "queue"),
        )


class SyncBaselineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_job(self, job_id: str) -> SyncBaseline | None:
        row = self.session.query(SyncBaselineModel).filter_by(job_id=job_id).one_or_none()
        if row is None:
            return None
        entries = (
            self.session.query(SyncBaselineEntryModel)
            .filter_by(baseline_id=row.id)
            .order_by(SyncBaselineEntryModel.path)
            .all()
        )
        return SyncBaseline(
            id=row.id,
            job_id=row.job_id,
            profile_id=row.profile_id,
            local_root=row.local_root,
            remote_root=row.remote_root,
            created_at=row.created_at,
            completed_at=row.completed_at,
            entries={
                entry.path: SyncBaselineEntry(
                    path=entry.path,
                    local=SyncFileState.from_dict(entry.local_state),
                    remote=SyncFileState.from_dict(entry.remote_state),
                )
                for entry in entries
            },
        )

    def replace(self, baseline: SyncBaseline) -> None:
        existing = self.session.query(SyncBaselineModel).filter_by(job_id=baseline.job_id).one_or_none()
        if existing is not None:
            self.session.query(SyncBaselineEntryModel).filter_by(baseline_id=existing.id).delete()
            self.session.delete(existing)
            self.session.flush()
        self.session.add(
            SyncBaselineModel(
                id=baseline.id,
                job_id=baseline.job_id,
                profile_id=baseline.profile_id,
                local_root=baseline.local_root,
                remote_root=baseline.remote_root,
                created_at=baseline.created_at,
                completed_at=baseline.completed_at,
            )
        )
        self.session.flush()
        for entry in baseline.entries.values():
            self.session.add(
                SyncBaselineEntryModel(
                    baseline_id=baseline.id,
                    path=entry.path,
                    local_state=entry.local.to_dict(),
                    remote_state=entry.remote.to_dict(),
                )
            )


class DeploymentJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: DeploymentJob) -> None:
        options = dict(job.options)
        options.update(
            {
                "profile_id": job.profile_id,
                "mode": job.mode.value,
                "local_project_folder": job.local_project_folder,
                "ignore_patterns": list(job.ignore_patterns),
                "run_local_build": job.run_local_build,
                "local_build_command": job.local_build_command,
                "chmod_enabled": job.chmod_enabled,
                "chmod_mode": job.chmod_mode,
                "post_deploy_command": job.post_deploy_command,
                "cache_clear_command": job.cache_clear_command,
                "restart_command": job.restart_command,
                "backup_directory": job.backup_directory,
                "backup_retention": job.backup_retention,
                "auto_rollback": job.auto_rollback,
                "strategy": job.strategy.value,
                "release_retention": job.release_retention,
                "health_check": {
                    "command": job.health_check.command,
                    "http_url": job.health_check.http_url,
                    "http_origin": job.health_check.http_origin.value,
                    "attempts": job.health_check.attempts,
                    "timeout_seconds": job.health_check.timeout_seconds,
                    "interval_seconds": job.health_check.interval_seconds,
                    "minimum_status": job.health_check.minimum_status,
                    "maximum_status": job.health_check.maximum_status,
                    "expected_substring": job.health_check.expected_substring,
                    "verify_tls": job.health_check.verify_tls,
                },
                "stale_lock_seconds": job.stale_lock_seconds,
                "history_retention": job.history_retention,
            }
        )
        self.session.merge(
            DeploymentJobModel(
                id=job.id,
                name=job.name,
                template=job.template,
                local_build_folder=job.local_build_folder,
                remote_target_folder=job.remote_target_folder,
                options=options,
            )
        )

    def list(self) -> list[DeploymentJob]:
        rows = self.session.query(DeploymentJobModel).order_by(DeploymentJobModel.name).all()
        return [self._to_job(row) for row in rows]

    def delete(self, job_id: str) -> None:
        row = self.session.get(DeploymentJobModel, job_id)
        if row is not None:
            self.session.delete(row)

    def _to_job(self, row: DeploymentJobModel) -> DeploymentJob:
        options = dict(row.options or {})
        try:
            mode = DeploymentMode(str(options.get("mode", DeploymentMode.UPLOAD_ONLY.value)))
        except ValueError:
            mode = DeploymentMode.UPLOAD_ONLY
        try:
            strategy = DeploymentStrategy(str(options.get("strategy", DeploymentStrategy.IN_PLACE.value)))
        except ValueError:
            strategy = DeploymentStrategy.IN_PLACE
        health_options = dict(options.get("health_check") or {})
        try:
            health_origin = HealthCheckOrigin(
                str(health_options.get("http_origin", HealthCheckOrigin.DESKTOP.value))
            )
        except ValueError:
            health_origin = HealthCheckOrigin.DESKTOP
        return DeploymentJob(
            id=row.id,
            name=row.name,
            template=row.template,
            local_build_folder=row.local_build_folder,
            remote_target_folder=row.remote_target_folder,
            options=options,
            profile_id=options.get("profile_id"),
            mode=mode,
            local_project_folder=str(options.get("local_project_folder") or ""),
            ignore_patterns=list(options.get("ignore_patterns") or []),
            run_local_build=bool(options.get("run_local_build", False)),
            local_build_command=str(options.get("local_build_command") or ""),
            chmod_enabled=bool(options.get("chmod_enabled", False)),
            chmod_mode=str(options.get("chmod_mode") or "755"),
            post_deploy_command=str(options.get("post_deploy_command") or ""),
            cache_clear_command=str(options.get("cache_clear_command") or ""),
            restart_command=str(options.get("restart_command") or ""),
            backup_directory=str(options.get("backup_directory") or ""),
            backup_retention=int(options.get("backup_retention", 5)),
            auto_rollback=bool(options.get("auto_rollback", True)),
            strategy=strategy,
            release_retention=int(options.get("release_retention", 5)),
            health_check=HealthCheckConfig(
                command=str(health_options.get("command") or ""),
                http_url=str(health_options.get("http_url") or ""),
                http_origin=health_origin,
                attempts=int(health_options.get("attempts", 3)),
                timeout_seconds=int(health_options.get("timeout_seconds", 10)),
                interval_seconds=int(health_options.get("interval_seconds", 2)),
                minimum_status=int(health_options.get("minimum_status", 200)),
                maximum_status=int(health_options.get("maximum_status", 399)),
                expected_substring=str(health_options.get("expected_substring") or ""),
                verify_tls=bool(health_options.get("verify_tls", True)),
            ),
            stale_lock_seconds=int(options.get("stale_lock_seconds", 7200)),
            history_retention=int(options.get("history_retention", 100)),
        )


class DeploymentRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, run: DeploymentRun) -> None:
        self.session.merge(
            DeploymentRunModel(
                id=run.id,
                job_id=run.job_id,
                profile_id=run.profile_id,
                profile_name=run.profile_name,
                host=run.host,
                remote_target=run.remote_target,
                strategy=run.strategy.value,
                action=run.action,
                status=run.status.value,
                started_at=run.started_at,
                finished_at=run.finished_at,
                uploads=run.uploads,
                overwrites=run.overwrites,
                deletes=run.deletes,
                bytes_total=run.bytes_total,
                health_ok=run.health_ok,
                artifact_path=run.artifact_path,
                rolled_back=run.rolled_back,
                rollback_error=run.rollback_error,
                message=run.message,
                preview_digest=run.preview_digest,
            )
        )

    def get(self, run_id: str) -> DeploymentRun | None:
        row = self.session.get(DeploymentRunModel, run_id)
        return self._to_run(row) if row else None

    def list_for_job(self, job_id: str, *, limit: int = 100) -> list[DeploymentRun]:
        rows = (
            self.session.query(DeploymentRunModel)
            .filter_by(job_id=job_id)
            .order_by(DeploymentRunModel.started_at.desc())
            .limit(max(1, int(limit)))
            .all()
        )
        return [self._to_run(row) for row in rows]

    def prune_for_job(self, job_id: str, *, keep: int = 100) -> None:
        rows = (
            self.session.query(DeploymentRunModel)
            .filter_by(job_id=job_id)
            .order_by(DeploymentRunModel.started_at.desc())
            .offset(max(1, int(keep)))
            .all()
        )
        for row in rows:
            self.session.query(DeploymentRunStageModel).filter_by(run_id=row.id).delete()
            self.session.delete(row)

    def _to_run(self, row: DeploymentRunModel) -> DeploymentRun:
        return DeploymentRun(
            id=row.id,
            job_id=row.job_id,
            profile_id=row.profile_id,
            profile_name=row.profile_name,
            host=row.host,
            remote_target=row.remote_target,
            strategy=DeploymentStrategy(row.strategy),
            action=row.action,
            status=DeploymentRunStatus(row.status),
            started_at=row.started_at,
            finished_at=row.finished_at,
            uploads=row.uploads,
            overwrites=row.overwrites,
            deletes=row.deletes,
            bytes_total=row.bytes_total,
            health_ok=row.health_ok,
            artifact_path=row.artifact_path,
            rolled_back=row.rolled_back,
            rollback_error=row.rollback_error,
            message=row.message,
            preview_digest=row.preview_digest,
        )


class DeploymentStageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: DeploymentStageRecord) -> None:
        self.session.merge(
            DeploymentRunStageModel(
                id=record.id,
                run_id=record.run_id,
                stage=record.stage.value,
                level=record.level,
                message=record.message,
                sequence=record.sequence,
                started_at=record.started_at,
                finished_at=record.finished_at,
                output_excerpt=record.output_excerpt,
            )
        )

    def get(self, record_id: str) -> DeploymentStageRecord | None:
        row = self.session.get(DeploymentRunStageModel, record_id)
        return self._to_record(row) if row else None

    def list_for_run(self, run_id: str) -> list[DeploymentStageRecord]:
        rows = (
            self.session.query(DeploymentRunStageModel)
            .filter_by(run_id=run_id)
            .order_by(DeploymentRunStageModel.sequence)
            .all()
        )
        return [self._to_record(row) for row in rows]

    def _to_record(self, row: DeploymentRunStageModel) -> DeploymentStageRecord:
        return DeploymentStageRecord(
            id=row.id,
            run_id=row.run_id,
            stage=DeploymentStage(row.stage),
            level=row.level,
            message=row.message,
            sequence=row.sequence,
            started_at=row.started_at,
            finished_at=row.finished_at,
            output_excerpt=row.output_excerpt,
        )


class DeploymentArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, artifact: DeploymentArtifact) -> None:
        self.session.merge(
            DeploymentArtifactModel(
                id=artifact.id,
                run_id=artifact.run_id,
                job_id=artifact.job_id,
                profile_id=artifact.profile_id,
                kind=artifact.kind.value,
                path=artifact.path,
                format=artifact.format,
                created_at=artifact.created_at,
                active=artifact.active,
                restorable=artifact.restorable,
                imported=artifact.imported,
                artifact_metadata=artifact.metadata,
            )
        )

    def get(self, artifact_id: str) -> DeploymentArtifact | None:
        row = self.session.get(DeploymentArtifactModel, artifact_id)
        return self._to_artifact(row) if row else None

    def list_for_job(self, job_id: str, *, restorable_only: bool = False) -> list[DeploymentArtifact]:
        query = self.session.query(DeploymentArtifactModel).filter_by(job_id=job_id)
        if restorable_only:
            query = query.filter_by(restorable=True)
        rows = query.order_by(DeploymentArtifactModel.created_at.desc()).all()
        return [self._to_artifact(row) for row in rows]

    def find_by_path(self, job_id: str, path: str) -> DeploymentArtifact | None:
        row = (
            self.session.query(DeploymentArtifactModel)
            .filter_by(job_id=job_id, path=path)
            .one_or_none()
        )
        return self._to_artifact(row) if row else None

    def set_active(self, job_id: str, path: str | None) -> None:
        self.session.query(DeploymentArtifactModel).filter_by(
            job_id=job_id,
            kind=DeploymentArtifactKind.RELEASE.value,
        ).update({"active": False})
        if path:
            self.session.query(DeploymentArtifactModel).filter_by(
                job_id=job_id,
                path=path,
            ).update({"active": True})

    def apply_retention(
        self,
        job_id: str,
        kind: DeploymentArtifactKind,
        *,
        keep: int,
        protected_paths: set[str] | None = None,
    ) -> None:
        rows = (
            self.session.query(DeploymentArtifactModel)
            .filter_by(job_id=job_id, kind=kind.value)
            .order_by(DeploymentArtifactModel.created_at.desc())
            .all()
        )
        protected = protected_paths or set()
        retained_paths = set(protected)
        for row in rows:
            if row.path in protected:
                continue
            if len(retained_paths) < max(1, int(keep)):
                retained_paths.add(row.path)
        for row in rows:
            row.restorable = row.path in retained_paths

    def _to_artifact(self, row: DeploymentArtifactModel) -> DeploymentArtifact:
        return DeploymentArtifact(
            id=row.id,
            run_id=row.run_id,
            job_id=row.job_id,
            profile_id=row.profile_id,
            kind=DeploymentArtifactKind(row.kind),
            path=row.path,
            format=row.format,
            created_at=row.created_at,
            active=row.active,
            restorable=row.restorable,
            imported=row.imported,
            metadata=dict(row.artifact_metadata or {}),
        )


class PlaybookRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_snippet(self, recipe: PlaybookRecipe) -> None:
        model = CustomPlaybookSnippetModel(
            id=recipe.id,
            title=recipe.title,
            category=str(recipe.category),
            safety=str(recipe.safety),
            safety_label=recipe.safety_label,
            description=recipe.description,
            script_template=recipe.script_template,
            variables_json=[v.to_dict() for v in recipe.variables],
            steps_json=list(recipe.steps),
            is_favorite=recipe.is_favorite,
            created_at=recipe.created_at,
        )
        self.session.merge(model)
        self.session.commit()

    def get_snippet(self, snippet_id: str) -> PlaybookRecipe | None:
        row = self.session.get(CustomPlaybookSnippetModel, snippet_id)
        return self._to_recipe(row) if row else None

    def list_custom_snippets(self) -> list[PlaybookRecipe]:
        rows = (
            self.session.query(CustomPlaybookSnippetModel)
            .order_by(CustomPlaybookSnippetModel.created_at.desc())
            .all()
        )
        return [self._to_recipe(r) for r in rows]

    def delete_snippet(self, snippet_id: str) -> bool:
        row = self.session.get(CustomPlaybookSnippetModel, snippet_id)
        if row:
            self.session.delete(row)
            self.session.commit()
            return True
        return False

    def toggle_favorite(self, snippet_id: str) -> bool:
        row = self.session.get(CustomPlaybookSnippetModel, snippet_id)
        if row:
            row.is_favorite = not row.is_favorite
            self.session.commit()
            return row.is_favorite
        return False

    def record_execution(self, record: PlaybookExecutionRecord) -> None:
        model = PlaybookExecutionHistoryModel(
            id=record.id,
            playbook_id=record.recipe_id,
            profile_id=record.profile_id,
            executed_at=record.started_at,
            duration_ms=record.duration_ms,
            exit_code=record.exit_code,
            status=record.status,
            output_summary=record.log_output[:2000] if record.log_output else "",
        )
        self.session.merge(model)
        self.session.commit()

    def list_history(self, playbook_id: str | None = None, limit: int = 50) -> list[PlaybookExecutionRecord]:
        query = self.session.query(PlaybookExecutionHistoryModel)
        if playbook_id:
            query = query.filter_by(playbook_id=playbook_id)
        rows = query.order_by(PlaybookExecutionHistoryModel.executed_at.desc()).limit(limit).all()
        return [
            PlaybookExecutionRecord(
                id=r.id,
                recipe_id=r.playbook_id,
                recipe_title="",
                profile_id=r.profile_id,
                started_at=r.executed_at,
                duration_ms=r.duration_ms,
                exit_code=r.exit_code,
                status=r.status,
                log_output=r.output_summary,
            )
            for r in rows
        ]

    def _to_recipe(self, row: CustomPlaybookSnippetModel) -> PlaybookRecipe:
        variables = [PlaybookVariable.from_dict(v) for v in (row.variables_json or [])]
        return PlaybookRecipe(
            id=row.id,
            title=row.title,
            category=row.category,
            safety=row.safety,
            safety_label=row.safety_label,
            description=row.description,
            script_template=row.script_template,
            variables=variables,
            steps=list(row.steps_json or []),
            is_prebundled=False,
            is_favorite=bool(row.is_favorite),
            runtime_estimate="~5s",
            created_at=row.created_at,
        )

