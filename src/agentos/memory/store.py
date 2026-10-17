"""SQLite-backed episodic memory with provenance and optional expiry."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    content: str
    memory_type: str
    source: str
    confidence: float
    created_at: str
    expires_at: str | None
    metadata: dict[str, Any]


class SQLiteMemoryStore:
    """Small local memory store; callers remain responsible for sensitive-data policy."""

    def __init__(self, database: str | Path) -> None:
        raw_database = str(database)
        self._uri = raw_database == ":memory:"
        self.database = (
            f"file:agentos-{uuid.uuid4().hex}?mode=memory&cache=shared"
            if self._uri
            else raw_database
        )
        self._keeper: sqlite3.Connection | None = None
        if self._uri:
            self._keeper = sqlite3.connect(self.database, uri=True, timeout=10.0)
        else:
            Path(self.database).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10.0, uri=self._uri)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self) -> None:
        """Release the keeper connection used by an in-memory database."""
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_type_created "
                "ON memories(memory_type, created_at)"
            )

    def add(
        self,
        content: str,
        *,
        memory_type: str = "episodic",
        source: str,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> MemoryRecord:
        if not content.strip():
            raise ValueError("Memory content must not be empty.")
        if not memory_type.strip() or not source.strip():
            raise ValueError("Memory type and source must not be empty.")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0 and 1.")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("TTL must be a positive number of seconds.")

        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        record = MemoryRecord(
            memory_id=str(uuid.uuid4()),
            content=content,
            memory_type=memory_type,
            source=source,
            confidence=confidence,
            created_at=now.isoformat(),
            expires_at=expires.isoformat() if expires else None,
            metadata=metadata or {},
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories
                (memory_id, content, memory_type, source, confidence,
                 created_at, expires_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.content,
                    record.memory_type,
                    record.source,
                    record.confidence,
                    record.created_at,
                    record.expires_at,
                    json.dumps(record.metadata, sort_keys=True),
                ),
            )
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        if row is None or self._is_expired(row["expires_at"]):
            return None
        return self._to_record(row)

    def search(
        self,
        query: str = "",
        *,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        if limit < 1 or limit > 500:
            raise ValueError("Search limit must be between 1 and 500.")
        clauses = ["(expires_at IS NULL OR expires_at > ?)"]
        params: list[Any] = [datetime.now(UTC).isoformat()]
        if query:
            clauses.append("content LIKE ?")
            params.append(f"%{query}%")
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)
        params.append(limit)
        sql = (
            "SELECT * FROM memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._to_record(row) for row in rows]

    def delete(self, memory_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE memory_id = ?", (memory_id,)
            )
        return cursor.rowcount > 0

    def purge_expired(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
        return cursor.rowcount

    @staticmethod
    def _is_expired(expires_at: str | None) -> bool:
        return expires_at is not None and expires_at <= datetime.now(UTC).isoformat()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            content=row["content"],
            memory_type=row["memory_type"],
            source=row["source"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            metadata=json.loads(row["metadata_json"]),
        )
