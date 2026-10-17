import json

import pytest

from agentos.core.config import RuntimeConfig


def test_config_defaults_and_mapping() -> None:
    defaults = RuntimeConfig()
    assert defaults.max_plan_steps == 20
    configured = RuntimeConfig.from_mapping(
        {"max_plan_steps": 12, "audit_enabled": False}
    )
    assert configured.max_plan_steps == 12
    assert configured.audit_enabled is False


def test_config_rejects_unknown_and_invalid_values() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        RuntimeConfig.from_mapping({"enable_everything": True})
    with pytest.raises(ValueError):
        RuntimeConfig.from_mapping({"max_plan_steps": 0})
    with pytest.raises(ValueError):
        RuntimeConfig.from_mapping({"log_level": "VERBOSE"})
    with pytest.raises(ValueError):
        RuntimeConfig.from_mapping({"max_plan_steps": "many"})
    with pytest.raises(ValueError):
        RuntimeConfig.from_mapping({"audit_enabled": "yes"})


def test_config_loads_json_file(tmp_path) -> None:
    path = tmp_path / "agentos.json"
    path.write_text(json.dumps({"database_path": "state/db.sqlite3"}), encoding="utf-8")
    config = RuntimeConfig.from_json_file(path)
    assert config.database_path == "state/db.sqlite3"


def test_config_rejects_non_object_json(tmp_path) -> None:
    path = tmp_path / "agentos.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        RuntimeConfig.from_json_file(path)
