"""Persistent SQLite audit sink for tool execution events."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


class SQLiteAuditSink:
    """Append-only-by-interface audit persistence; not tamper-evident yet."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        Path(self.database).expanduser().resolve().parent.mkdir(
            parents=True, exist_ok=True
        )
        with closing(sqlite3.connect(self.database, timeout=10.0)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    outcome TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_timestamp "
                "ON audit_events(timestamp)"
            )
            connection.commit()

    def write(
        self, timestamp: str, tool_name: str, allowed: bool, outcome: str
    ) -> None:
        with closing(sqlite3.connect(self.database, timeout=10.0)) as connection:
            connection.execute(
                """
                INSERT INTO audit_events(timestamp, tool_name, allowed, outcome)
                VALUES (?, ?, ?, ?)
                """,
                (timestamp, tool_name, int(allowed), outcome),
            )
            connection.commit()

    def list_events(self, *, limit: int = 100) -> list[dict[str, object]]:
        if limit < 1 or limit > 1000:
            raise ValueError("Audit limit must be between 1 and 1000.")
        with closing(sqlite3.connect(self.database, timeout=10.0)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT event_id, timestamp, tool_name, allowed, outcome
                FROM audit_events ORDER BY event_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
