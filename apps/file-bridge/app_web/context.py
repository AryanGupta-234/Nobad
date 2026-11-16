"""Shared state for the web UI process: the app data service and the settings store.

Created once at start-up and passed to every API handler, so handlers stay plain functions that are easy to test
with a temporary database."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app_web.settings_store import SettingsStore
from storage.app_data import AppDataService

APP_NAME = "NOBAD File Bridge"


def app_version() -> str:
    try:
        from importlib.metadata import version

        return version("nobad-file-bridge")
    except Exception:
        return "0.4.0"


@dataclass
class AppContext:
    app_data: AppDataService
    settings: SettingsStore = field(init=False)
    version: str = field(default_factory=app_version)

    def __post_init__(self) -> None:
        self.settings = SettingsStore(self.app_data)

    @classmethod
    def create(cls, db_path: str | Path | None = None) -> "AppContext":
        return cls(AppDataService.create(db_path))
