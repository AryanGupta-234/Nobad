from __future__ import annotations

import json

from sqlalchemy import inspect

from credentials.crypto import KdfConfig
from credentials.env_parser import format_env, parse_env
from credentials.import_export import CredentialImportExportService
from credentials.models import CredentialKind
from credentials.vault_service import CredentialVaultService
from storage.database import init_database
from storage.models import (
    CredentialAuditEventModel,
    CredentialCustomFieldModel,
    CredentialItemModel,
    CredentialVaultMetadataModel,
)


def _vault(path) -> CredentialVaultService:  # type: ignore[no-untyped-def]
    service = CredentialVaultService(init_database(path))
    service._kdf_config = KdfConfig(time_cost=1, memory_cost=1024, parallelism=1)
    return service


def _import_export(vault: CredentialVaultService) -> CredentialImportExportService:
    service = CredentialImportExportService(vault)
    service._kdf_config = KdfConfig(time_cost=1, memory_cost=1024, parallelism=1)
    return service


def test_credentials_tables_are_created(tmp_path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    engine = session_factory.kw["bind"]
    tables = set(inspect(engine).get_table_names())

    assert "credential_vault_metadata" in tables
    assert "credential_projects" in tables
    assert "credential_items" in tables
    assert "credential_custom_fields" in tables
    assert "credential_audit_events" in tables


def test_vault_round_trip_never_persists_plaintext(tmp_path) -> None:
    vault = _vault(tmp_path / "app.sqlite3")

    assert vault.create_vault("correct-password").ok
    project = vault.create_project("Client Portal").data
    added = vault.add_item(
        project_id=project.id,
        title="GitHub token",
        kind=CredentialKind.GIT_TOKEN,
        secret_value="ghp_super_secret_token",
        username="deploy-bot",
        url_host="github.com",
        notes="private recovery note",
        custom_fields={"scope": "repo,workflow"},
        tags=["git", "ci"],
    )

    assert added.ok
    assert vault.reveal_secret(added.data.id).data == "ghp_super_secret_token"
    assert vault.reveal_notes(added.data.id).data == "private recovery note"
    assert vault.reveal_custom_fields(added.data.id).data == {"scope": "repo,workflow"}

    with vault.session_factory() as session:
        rows = [
            *session.query(CredentialVaultMetadataModel).all(),
            *session.query(CredentialItemModel).all(),
            *session.query(CredentialCustomFieldModel).all(),
            *session.query(CredentialAuditEventModel).all(),
        ]
        dump = "\n".join(repr(row.__dict__) for row in rows)

    assert "ghp_super_secret_token" not in dump
    assert "private recovery note" not in dump
    assert "repo,workflow" not in dump


def test_unlock_wrong_password_fails_and_master_password_can_rotate(tmp_path) -> None:
    vault = _vault(tmp_path / "app.sqlite3")
    vault.create_vault("old-password")
    project = vault.create_project("Production").data
    item = vault.add_item(
        project_id=project.id,
        title="Hosting login",
        kind=CredentialKind.HOSTING_PROVIDER,
        secret_value="panel-password",
        username="admin",
    ).data

    vault.lock()
    assert not vault.unlock("wrong-password").ok
    assert vault.unlock("old-password").ok
    assert vault.change_master_password("old-password", "new-password").ok

    vault.lock()
    assert not vault.unlock("old-password").ok
    assert vault.unlock("new-password").ok
    assert vault.reveal_secret(item.id).data == "panel-password"


def test_tampered_credential_blob_fails_to_decrypt(tmp_path) -> None:
    vault = _vault(tmp_path / "app.sqlite3")
    vault.create_vault("correct-password")
    project = vault.create_project("API").data
    item = vault.add_item(
        project_id=project.id,
        title="API key",
        kind=CredentialKind.API_KEY,
        secret_value="api-secret",
    ).data

    with vault.session_factory() as session:
        row = session.get(CredentialItemModel, item.id)
        payload = json.loads(row.encrypted_value)
        payload["ciphertext"] = payload["ciphertext"][:-2] + "AA"
        row.encrypted_value = json.dumps(payload)
        session.commit()

    result = vault.reveal_secret(item.id)

    assert not result.ok
    assert "decrypt" in result.message.lower()


def test_env_import_export_handles_common_syntax(tmp_path) -> None:
    entries = parse_env(
        """
        # comment
        export API_KEY="abc 123"
        EMPTY=
        MULTI="line1\\nline2"
        URL=https://example.com # inline comment
        """
    )

    assert [(entry.key, entry.value) for entry in entries] == [
        ("API_KEY", "abc 123"),
        ("EMPTY", ""),
        ("MULTI", "line1\nline2"),
        ("URL", "https://example.com"),
    ]
    assert 'API_KEY="abc 123"' in format_env(entries)

    vault = _vault(tmp_path / "app.sqlite3")
    vault.create_vault("correct-password")
    project = vault.create_project("Env Project").data
    io_service = _import_export(vault)

    preview = io_service.preview_env_import(project.id, "API_KEY=abc\nTOKEN=xyz\n")
    result = io_service.import_env(project.id, "API_KEY=abc\nTOKEN=xyz\n")
    exported = io_service.export_env(project.id)

    assert preview.creates == 2
    assert result.ok
    assert "API_KEY=abc" in exported.data
    assert "TOKEN=xyz" in exported.data


def test_loose_text_bulk_import_previews_and_saves_into_selected_project(tmp_path) -> None:
    vault = _vault(tmp_path / "app.sqlite3")
    vault.create_vault("correct-password")
    project = vault.create_project("Client Notes").data
    io_service = _import_export(vault)
    text = """
    Server Credentials
    URL : ssh -p 65002 deploy@example.com
    Password : server-secret

    GOOGLE_API_KEY=gemini-secret
    MONGO_URI=mongodb+srv://user:pass@example.mongodb.net/app

    AWS Credentials
    AWS Console:[Sign-in Link](https://123456789012.signin.aws.amazon.com/console)
    Username: ops@example.com
    Password: aws-secret
    """

    preview = io_service.preview_loose_text_import(project.id, text)
    imported = io_service.import_loose_text(project.id, text)
    items = vault.list_items(project.id)

    assert preview.ok
    assert preview.data["preview"].entries == 4
    assert preview.data["preview"].creates == 4
    assert imported.ok
    assert imported.data["created"] == 4
    assert {item.kind for item in items} >= {
        CredentialKind.SERVER_LOGIN,
        CredentialKind.API_KEY,
        CredentialKind.DATABASE,
        CredentialKind.CLOUD_PROVIDER,
    }
    server = next(item for item in items if item.kind == CredentialKind.SERVER_LOGIN)
    assert server.username == "deploy"
    assert server.url_host == "example.com:65002"
    assert vault.reveal_secret(server.id).data == "server-secret"


def test_loose_text_bulk_import_overwrites_duplicate_env_secret(tmp_path) -> None:
    vault = _vault(tmp_path / "app.sqlite3")
    vault.create_vault("correct-password")
    project = vault.create_project("Env Project").data
    io_service = _import_export(vault)

    assert io_service.import_loose_text(project.id, "GOOGLE_API_KEY=first").ok
    result = io_service.import_loose_text(project.id, "GOOGLE_API_KEY=second", conflict_policy="overwrite")
    item = vault.list_items(project.id)[0]

    assert result.ok
    assert result.data["updated"] == 1
    assert len(vault.list_items(project.id)) == 1
    assert vault.reveal_secret(item.id).data == "second"


def test_loose_text_bulk_import_renames_duplicate_env_key(tmp_path) -> None:
    vault = _vault(tmp_path / "app.sqlite3")
    vault.create_vault("correct-password")
    project = vault.create_project("Env Project").data
    io_service = _import_export(vault)

    assert io_service.import_loose_text(project.id, "GOOGLE_API_KEY=first").ok
    result = io_service.import_loose_text(project.id, "GOOGLE_API_KEY=second", conflict_policy="rename")
    keys = sorted(item.environment_key for item in vault.list_items(project.id))

    assert result.ok
    assert result.data["renamed"] == 1
    assert keys == ["GOOGLE_API_KEY", "GOOGLE_API_KEY_2"]


def test_encrypted_vault_export_import_round_trip(tmp_path) -> None:
    source = _vault(tmp_path / "source.sqlite3")
    source.create_vault("source-password")
    project = source.create_project("All Providers").data
    item = source.add_item(
        project_id=project.id,
        title="DNS provider token",
        kind=CredentialKind.DNS_CDN,
        secret_value="dns-secret",
        url_host="dns.example",
    ).data
    exporter = _import_export(source)

    exported = exporter.export_encrypted([project.id], "export-password")

    target = _vault(tmp_path / "target.sqlite3")
    target.create_vault("target-password")
    importer = _import_export(target)
    imported = importer.import_encrypted(exported.data, "export-password")
    imported_project = target.list_projects()[0]
    imported_item = target.list_items(imported_project.id)[0]

    assert exported.ok
    assert imported.ok
    assert imported_project.name == "All Providers"
    assert imported_item.title == item.title
    assert target.reveal_secret(imported_item.id).data == "dns-secret"
