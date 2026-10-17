from agentos.memory.store import SQLiteMemoryStore


def test_memory_persists_and_preserves_provenance(tmp_path) -> None:
    database = tmp_path / "agentos.sqlite3"
    store = SQLiteMemoryStore(database)
    record = store.add(
        "Task completed successfully",
        source="unit-test",
        confidence=0.85,
        metadata={"task_id": "task-1"},
    )

    reopened = SQLiteMemoryStore(database)
    loaded = reopened.get(record.memory_id)
    assert loaded is not None
    assert loaded.content == record.content
    assert loaded.source == "unit-test"
    assert loaded.confidence == 0.85
    assert loaded.metadata == {"task_id": "task-1"}


def test_memory_search_filters_type_and_content(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    store.add("User prefers concise reports", source="feedback", memory_type="semantic")
    store.add("Build task passed tests", source="runner", memory_type="episodic")

    results = store.search("task", memory_type="episodic")
    assert len(results) == 1
    assert results[0].source == "runner"


def test_memory_delete_and_expiry_cleanup(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    record = store.add("Temporary working context", source="runtime", ttl_seconds=60)
    assert store.get(record.memory_id) is not None
    assert store.delete(record.memory_id)
    assert store.get(record.memory_id) is None


def test_memory_validates_inputs(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    import pytest

    with pytest.raises(ValueError):
        store.add(" ", source="test")
    with pytest.raises(ValueError):
        store.add("valid", source="test", confidence=1.5)
    with pytest.raises(ValueError):
        store.search(limit=0)
