from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from sqlalchemy.orm import Session, sessionmaker

from security.credential_store import CredentialStore
from storage.database import init_database
from storage.repositories import (
    AppSettingsRepository,
    ConnectionProfileRepository,
    CredentialAuditRepository,
    CredentialRepository,
    DeploymentJobRepository,
    DeploymentArtifactRepository,
    DeploymentRunRepository,
    DeploymentStageRepository,
    OperationLogRepository,
    KnownHostRepository,
    PlaybookRepository,
    RecentPathRepository,
    SecretReferenceRepository,
    SyncJobRepository,
    SyncBaselineRepository,
    TransferHistoryRepository,
)


@dataclass
class AppDataService:
    session_factory: sessionmaker[Session]
    credential_store: CredentialStore

    @classmethod
    def create(cls, db_path: str | Path | None = None) -> "AppDataService":
        try:
            session_factory = init_database(db_path)
        except Exception:
            fallback = Path(tempfile.gettempdir()) / "remote-file-manager" / "app.sqlite3"
            session_factory = init_database(fallback)
        return cls(
            session_factory=session_factory,
            credential_store=CredentialStore(),
        )

    def connection_profiles(self, session: Session) -> ConnectionProfileRepository:
        return ConnectionProfileRepository(session)

    def secret_refs(self, session: Session) -> SecretReferenceRepository:
        return SecretReferenceRepository(session)

    def settings(self, session: Session) -> AppSettingsRepository:
        return AppSettingsRepository(session)

    def logs(self, session: Session) -> OperationLogRepository:
        return OperationLogRepository(session)

    def known_hosts(self, session: Session) -> KnownHostRepository:
        return KnownHostRepository(session)

    def transfers(self, session: Session) -> TransferHistoryRepository:
        return TransferHistoryRepository(session)

    def recent_paths(self, session: Session) -> RecentPathRepository:
        return RecentPathRepository(session)

    def sync_jobs(self, session: Session) -> SyncJobRepository:
        return SyncJobRepository(session)

    def sync_baselines(self, session: Session) -> SyncBaselineRepository:
        return SyncBaselineRepository(session)

    def deployment_jobs(self, session: Session) -> DeploymentJobRepository:
        return DeploymentJobRepository(session)

    def deployment_runs(self, session: Session) -> DeploymentRunRepository:
        return DeploymentRunRepository(session)

    def deployment_stages(self, session: Session) -> DeploymentStageRepository:
        return DeploymentStageRepository(session)

    def deployment_artifacts(self, session: Session) -> DeploymentArtifactRepository:
        return DeploymentArtifactRepository(session)

    def credentials(self, session: Session) -> CredentialRepository:
        return CredentialRepository(session)

    def credential_audit(self, session: Session) -> CredentialAuditRepository:
        return CredentialAuditRepository(session)

    def playbooks(self, session: Session) -> PlaybookRepository:
        return PlaybookRepository(session)
