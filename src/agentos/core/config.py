"""Validated configuration loading for the local AgentOS runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    database_path: str = "data/agentos.sqlite3"
    max_plan_steps: int = 20
    tool_timeout_seconds: float = 30.0
    audit_enabled: bool = True
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, str) or not self.database_path.strip():
            raise ValueError("database_path must be a non-empty string.")
        if isinstance(self.max_plan_steps, bool) or not isinstance(self.max_plan_steps, int):
            raise ValueError("max_plan_steps must be an integer.")
        if not 1 <= self.max_plan_steps <= 500:
            raise ValueError("max_plan_steps must be between 1 and 500.")
        if isinstance(self.tool_timeout_seconds, bool) or not isinstance(
            self.tool_timeout_seconds, (int, float)
        ):
            raise ValueError("tool_timeout_seconds must be numeric.")
        if not 0.1 <= self.tool_timeout_seconds <= 3600:
            raise ValueError("tool_timeout_seconds must be between 0.1 and 3600.")
        if not isinstance(self.audit_enabled, bool):
            raise ValueError("audit_enabled must be a boolean.")
        if not isinstance(self.log_level, str) or self.log_level.upper() not in {
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
        }:
            raise ValueError("Unsupported log_level.")

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> RuntimeConfig:
        allowed = {
            "database_path",
            "max_plan_steps",
            "tool_timeout_seconds",
            "audit_enabled",
            "log_level",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
        try:
            return cls(**values)
        except TypeError as exc:
            raise ValueError(f"Invalid configuration values: {exc}") from exc

    @classmethod
    def from_json_file(cls, path: str | Path) -> RuntimeConfig:
        config_path = Path(path)
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON configuration: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("Configuration root must be a JSON object.")
        return cls.from_mapping(raw)
