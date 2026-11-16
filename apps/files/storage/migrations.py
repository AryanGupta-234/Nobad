from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, inspect, text
from sqlalchemy.engine import Engine


Migration = tuple[int, str, Callable[[Connection], None]]


def _connection_options(connection: Connection) -> None:
    inspector = inspect(connection)
    if "connection_profiles" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("connection_profiles")}
    if "options" not in columns:
        connection.execute(text("ALTER TABLE connection_profiles ADD COLUMN options JSON DEFAULT '{}'"))


def _credential_vault_tables(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS credential_vault_metadata ("
            "id INTEGER PRIMARY KEY, "
            "kdf_name VARCHAR NOT NULL, "
            "salt VARCHAR NOT NULL, "
            "kdf_params JSON DEFAULT '{}', "
            "verifier_payload TEXT NOT NULL, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
            ")"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS credential_projects ("
            "id VARCHAR PRIMARY KEY, "
            "name VARCHAR NOT NULL, "
            "description TEXT DEFAULT '', "
            "tags JSON DEFAULT '[]', "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
            ")"
        )
    )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_credential_projects_name ON credential_projects(name)"))
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS credential_items ("
            "id VARCHAR PRIMARY KEY, "
            "project_id VARCHAR NOT NULL REFERENCES credential_projects(id) ON DELETE CASCADE, "
            "title VARCHAR NOT NULL, "
            "kind VARCHAR NOT NULL, "
            "username VARCHAR DEFAULT '', "
            "url_host VARCHAR DEFAULT '', "
            "environment_key VARCHAR DEFAULT '', "
            "tags JSON DEFAULT '[]', "
            "favorite BOOLEAN DEFAULT 0, "
            "encrypted_value TEXT NOT NULL, "
            "encrypted_notes TEXT DEFAULT '', "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
            ")"
        )
    )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_credential_items_project_id ON credential_items(project_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_credential_items_title ON credential_items(title)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_credential_items_kind ON credential_items(kind)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_credential_items_environment_key ON credential_items(environment_key)"))
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS credential_custom_fields ("
            "id VARCHAR PRIMARY KEY, "
            "item_id VARCHAR NOT NULL REFERENCES credential_items(id) ON DELETE CASCADE, "
            "name VARCHAR NOT NULL, "
            "encrypted_value TEXT NOT NULL, "
            "is_secret BOOLEAN DEFAULT 1, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "CONSTRAINT uq_credential_custom_field_name UNIQUE (item_id, name)"
            ")"
        )
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_credential_custom_fields_item_id ON credential_custom_fields(item_id)")
    )
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS credential_audit_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project_id VARCHAR, "
            "item_id VARCHAR, "
            "action VARCHAR NOT NULL, "
            "message TEXT NOT NULL, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
            ")"
        )
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_credential_audit_events_project_id ON credential_audit_events(project_id)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_credential_audit_events_item_id ON credential_audit_events(item_id)")
    )


def _playbooks_snippets_tables(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS custom_playbook_snippets ("
            "id VARCHAR PRIMARY KEY, "
            "title VARCHAR NOT NULL, "
            "category VARCHAR DEFAULT 'custom', "
            "safety VARCHAR DEFAULT 'safe', "
            "safety_label VARCHAR DEFAULT 'Safe', "
            "description TEXT DEFAULT '', "
            "script_template TEXT NOT NULL, "
            "variables_json JSON DEFAULT '[]', "
            "steps_json JSON DEFAULT '[]', "
            "is_favorite BOOLEAN DEFAULT 0, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
            ")"
        )
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_custom_playbook_snippets_category ON custom_playbook_snippets(category)")
    )
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS playbook_execution_history ("
            "id VARCHAR PRIMARY KEY, "
            "playbook_id VARCHAR NOT NULL, "
            "profile_id VARCHAR, "
            "executed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "duration_ms INTEGER DEFAULT 0, "
            "exit_code INTEGER DEFAULT 0, "
            "status VARCHAR DEFAULT 'success', "
            "output_summary TEXT DEFAULT ''"
            ")"
        )
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_playbook_execution_history_playbook ON playbook_execution_history(playbook_id)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_playbook_execution_history_profile ON playbook_execution_history(profile_id)")
    )


MIGRATIONS: tuple[Migration, ...] = (
    (1, "connection profile options", _connection_options),
    (2, "credential vault tables", _credential_vault_tables),
    (3, "playbooks snippets tables", _playbooks_snippets_tables),
)


def run_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "name VARCHAR NOT NULL, "
                "applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
                ")"
            )
        )
        applied = {
            int(row[0])
            for row in connection.execute(text("SELECT version FROM schema_migrations")).fetchall()
        }
        for version, name, migration in MIGRATIONS:
            if version in applied:
                continue
            migration(connection)
            connection.execute(
                text("INSERT INTO schema_migrations(version, name) VALUES (:version, :name)"),
                {"version": version, "name": name},
            )
