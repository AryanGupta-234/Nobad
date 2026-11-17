"""Shared state for the web UI process: the app data service, the settings store and the window controller.

Created once at start-up and passed to every API handler, so handlers stay plain functions that are easy to test
with a temporary database."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app_web.settings_store import SettingsStore
from storage.app_data import AppDataService

APP_NAME = "NOBAD File Bridge"
WINDOW_GEOMETRY_ROW = "web_ui.window"


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
    window: Any = None            # app_web.window.WindowController, or None in --browser mode and tests

    session: Any = field(init=False)
    transfers: Any = field(init=False)
    terminals: Any = field(init=False)
    editor: Any = field(init=False)

    def __post_init__(self) -> None:
        from app_web.editor import EditorService
        from app_web.session import SessionService
        from app_web.terminals import TerminalService
        from app_web.transfers import TransferService

        self.settings = SettingsStore(self.app_data)
        self.session = SessionService(self.app_data)
        self.transfers = TransferService(max_concurrent=int(self.settings.get("transfer.max_concurrent")))
        self.terminals = TerminalService()
        self.editor = EditorService()
        self.session.on_closed.append(self.terminals.close_for_profile)

    @classmethod
    def create(cls, db_path: str | Path | None = None) -> "AppContext":
        return cls(AppDataService.create(db_path))

    # ---- window size and position (not a user-facing setting)
    def load_window_geometry(self) -> dict[str, Any] | None:
        with self.app_data.session_factory() as session:
            stored = self.app_data.settings(session).get(WINDOW_GEOMETRY_ROW)
        value = stored.get("value") if isinstance(stored, dict) else None
        return value if isinstance(value, dict) else None

    def save_window_geometry(self, geometry: dict[str, Any]) -> None:
        clean = {k: v for k, v in geometry.items() if k in {"x", "y", "w", "h", "maximized"}}
        with self.app_data.session_factory() as session:
            self.app_data.settings(session).set(WINDOW_GEOMETRY_ROW, {"value": clean})
            session.commit()
