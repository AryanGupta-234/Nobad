from agentos.core.audit import SQLiteAuditSink


def test_audit_sink_persists_events(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    sink = SQLiteAuditSink(database)
    sink.write("2026-10-17T00:00:00+00:00", "notes.search", True, "Execution completed.")

    reopened = SQLiteAuditSink(database)
    events = reopened.list_events()
    assert len(events) == 1
    assert events[0]["tool_name"] == "notes.search"
    assert events[0]["allowed"] == 1


def test_audit_sink_validates_limit(tmp_path) -> None:
    import pytest

    sink = SQLiteAuditSink(tmp_path / "audit.sqlite3")
    with pytest.raises(ValueError):
        sink.list_events(limit=0)
