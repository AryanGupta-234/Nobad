from agentos.memory.store import SQLiteMemoryStore


def test_in_memory_store_keeps_data_between_operations() -> None:
    store = SQLiteMemoryStore(":memory:")
    try:
        saved = store.add("Transient task context", source="test", memory_type="working")
        loaded = store.get(saved.memory_id)
        assert loaded is not None
        assert loaded.content == "Transient task context"
        assert store.search(memory_type="working")[0].memory_id == saved.memory_id
    finally:
        store.close()
