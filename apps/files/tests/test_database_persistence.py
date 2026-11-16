from __future__ import annotations

from dataclasses import replace

from sqlalchemy import inspect

from core.connections.profile import AuthType, ConnectionProfile
from deployment.deployment_job import (
    DeploymentJob,
    DeploymentMode,
    DeploymentStrategy,
    HealthCheckConfig,
    HealthCheckOrigin,
)
from security.credential_store import InMemoryCredentialStore
from storage.database import init_database
from storage.models import ConnectionProfileModel, SecureSecretReferenceModel
from storage.saved_connections import SavedConnectionService
from sync.sync_job import SyncJob, SyncMode


def test_db_initialization_creates_expected_tables(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    engine = session_factory.kw["bind"]
    tables = set(inspect(engine).get_table_names())

    assert "connection_profiles" in tables
    assert "secure_secret_references" in tables
    assert "transfer_history" in tables
    assert "operation_logs" in tables
    assert "sync_jobs" in tables
    assert "deployment_runs" in tables
    assert "deployment_run_stages" in tables
    assert "deployment_artifacts" in tables
    assert "credential_vault_metadata" in tables
    assert "credential_projects" in tables
    assert "credential_items" in tables
    assert "credential_custom_fields" in tables
    assert "credential_audit_events" in tables


def test_saved_connection_round_trip_does_not_store_plaintext_secret(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    service = SavedConnectionService(session_factory, InMemoryCredentialStore())
    profile = ConnectionProfile.quick_sftp(
        host="example.com",
        port=22,
        username="user",
        auth_type=AuthType.PASSWORD,
    )

    result = service.save_profile(profile, secret="super-secret", remember_secret=True)

    assert result.ok
    with session_factory() as session:
        stored = session.get(ConnectionProfileModel, profile.id)
        refs = session.query(SecureSecretReferenceModel).all()
        assert stored is not None
        assert stored.password_secret_ref == refs[0].id
        assert "super-secret" not in repr(stored.__dict__)
        assert "super-secret" not in repr(refs[0].__dict__)

    loaded = service.load_profile_secret(service.list_profiles()[0])
    assert loaded.ok
    assert loaded.data.password == "super-secret"


def test_saved_connection_custom_name_and_rename_round_trip(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    service = SavedConnectionService(session_factory, InMemoryCredentialStore())
    profile = ConnectionProfile.quick_sftp(
        name="Production Site",
        host="example.com",
        port=22,
        username="user",
        auth_type=AuthType.PASSWORD,
    )

    save_result = service.save_profile(profile)
    rename_result = service.rename_profile(profile.id, "Client Production")

    assert save_result.ok
    assert rename_result.ok
    assert service.list_profiles()[0].name == "Client Production"


def test_saved_connection_rejects_empty_rename(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    service = SavedConnectionService(session_factory, InMemoryCredentialStore())
    profile = ConnectionProfile.quick_sftp(
        name="Production Site",
        host="example.com",
        port=22,
        username="user",
        auth_type=AuthType.PASSWORD,
    )

    service.save_profile(profile)
    result = service.rename_profile(profile.id, "  ")

    assert not result.ok
    assert service.list_profiles()[0].name == "Production Site"


def test_saved_connection_edit_keeps_replaces_and_removes_keyring_secret(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    credential_store = InMemoryCredentialStore()
    service = SavedConnectionService(session_factory, credential_store)
    profile = ConnectionProfile.quick_sftp(
        name="Production Site",
        host="example.com",
        port=22,
        username="user",
        auth_type=AuthType.PASSWORD,
    )
    service.save_profile(profile, secret="original-secret", remember_secret=True)

    saved = service.list_profiles()[0]
    kept = service.update_profile(
        replace(saved, host="new.example.com"),
        remember_secret=True,
    )
    kept_profile = service.list_profiles()[0]
    kept_secret = service.load_profile_secret(kept_profile)

    assert kept.ok
    assert kept_profile.host == "new.example.com"
    assert kept_secret.ok
    assert kept_secret.data.password == "original-secret"

    replaced = service.update_profile(
        replace(kept_profile, username="deploy"),
        secret="replacement-secret",
        remember_secret=True,
    )
    replaced_profile = service.list_profiles()[0]
    replaced_secret = service.load_profile_secret(replaced_profile)

    assert replaced.ok
    assert replaced_secret.data.password == "replacement-secret"
    with session_factory() as session:
        assert session.query(SecureSecretReferenceModel).count() == 1

    removed = service.update_profile(replaced_profile, remember_secret=False)
    removed_profile = service.list_profiles()[0]

    assert removed.ok
    assert removed_profile.password_secret_ref is None
    with session_factory() as session:
        assert session.query(SecureSecretReferenceModel).count() == 0


def test_app_settings_store_transfer_and_terminal_preferences(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    with session_factory() as session:
        from storage.repositories import AppSettingsRepository

        repo = AppSettingsRepository(session)
        repo.set("transfer.max_concurrent", {"value": 3})
        repo.set(
            "terminal",
            {
                "value": {
                    "profiles": [{"name": "Default Shell", "startup_command": "pwd"}],
                    "default_profile": "Default Shell",
                    "font_size": 14,
                    "scrollback": 6000,
                }
            },
        )
        session.commit()

    with session_factory() as session:
        from storage.repositories import AppSettingsRepository

        repo = AppSettingsRepository(session)
        assert repo.get("transfer.max_concurrent") == {"value": 3}
        assert repo.get("terminal")["value"]["profiles"][0]["startup_command"] == "pwd"


def test_sync_job_repository_round_trip(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    job = SyncJob(
        name="Upload Site",
        mode=SyncMode.LOCAL_TO_REMOTE,
        source_path="/local/site",
        destination_path="/remote/site",
        ignore_patterns=["node_modules", ".git"],
    )

    with session_factory() as session:
        repo = __import__("storage.repositories", fromlist=["SyncJobRepository"]).SyncJobRepository(session)
        repo.add(job)
        session.commit()

    with session_factory() as session:
        repo = __import__("storage.repositories", fromlist=["SyncJobRepository"]).SyncJobRepository(session)
        loaded = repo.list()[0]

    assert loaded.id == job.id
    assert loaded.name == "Upload Site"
    assert loaded.mode == SyncMode.LOCAL_TO_REMOTE
    assert loaded.ignore_patterns == ["node_modules", ".git"]


def test_deployment_job_repository_round_trip_uses_options_json(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    job = DeploymentJob(
        name="Production",
        template="Node App",
        profile_id="profile-1",
        mode=DeploymentMode.MIRROR,
        local_project_folder="/project",
        local_build_folder="/project/dist",
        remote_target_folder="/var/www/site",
        ignore_patterns=[".git", ".env"],
        run_local_build=True,
        local_build_command="npm run build",
        restart_command="systemctl restart site",
        backup_directory="/var/backups/rfm",
        backup_retention=5,
        strategy=DeploymentStrategy.ATOMIC_RELEASE,
        release_retention=7,
        health_check=HealthCheckConfig(
            command="test -f public/index.html",
            http_url="https://example.com/health",
            http_origin=HealthCheckOrigin.REMOTE,
            expected_substring="ok",
        ),
    )

    with session_factory() as session:
        from storage.repositories import DeploymentJobRepository

        DeploymentJobRepository(session).add(job)
        session.commit()

    with session_factory() as session:
        from storage.models import DeploymentJobModel
        from storage.repositories import DeploymentJobRepository

        row = session.get(DeploymentJobModel, job.id)
        loaded = DeploymentJobRepository(session).list()[0]

    assert row is not None
    assert loaded.profile_id == "profile-1"
    assert loaded.mode == DeploymentMode.MIRROR
    assert loaded.local_build_command == "npm run build"
    assert loaded.restart_command == "systemctl restart site"
    assert loaded.strategy == DeploymentStrategy.ATOMIC_RELEASE
    assert loaded.release_retention == 7
    assert loaded.health_check.http_origin == HealthCheckOrigin.REMOTE
    assert loaded.health_check.expected_substring == "ok"
    assert "password" not in repr(row.options).lower()
