"""Settings for the web UI, in the same database rows the Qt UI uses (so both UIs share them).

Each field is declared once in ``FIELDS``: where it is stored, its type and limits, and the text shown in Settings.
The page draws its form from ``schema()``, and every change is validated by ``coerce`` here, so the UI can't store
a value the backend wouldn't accept. Only settings that really change something are listed (UI text never claims
more than the code does)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from storage.app_data import AppDataService

MAX_TEXT = 260


@dataclass(frozen=True)
class SettingField:
    id: str                       # stable id used by the page, e.g. "terminal.font_size"
    row: str                      # database row key, e.g. "terminal"
    path: tuple[str, ...]         # path inside the row's value; () = the value itself
    kind: str                     # "choice" | "int" | "text" | "bool"
    default: Any
    group: str
    label: str
    description: str
    choices: tuple[tuple[str, str], ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    placeholder: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)


GROUPS: tuple[tuple[str, str], ...] = (
    ("appearance", "Appearance"),
    ("transfers", "Transfers"),
    ("files", "Files"),
    ("terminal", "Terminal"),
    ("tools", "Tools"),
)

FIELDS: tuple[SettingField, ...] = (
    SettingField(
        "web_ui.theme", "web_ui", ("theme",), "choice", "dark", "appearance", "Theme",
        "Dark or light. System follows your Windows or desktop setting.",
        choices=(("dark", "Dark"), ("light", "Light"), ("system", "System")),
        keywords=("dark mode", "light mode", "colour", "color"),
    ),
    SettingField(
        "web_ui.custom_titlebar", "web_ui", ("custom_titlebar",), "bool", True, "appearance", "NOBAD title bar",
        "NOBAD's own top bar with minimise, maximise and close. Off brings back the standard Windows title bar. "
        "Applies the next time File Bridge starts.",
        keywords=("window", "title bar", "frame", "buttons"),
    ),
    SettingField(
        "transfer.max_concurrent", "transfer.max_concurrent", (), "int", 3, "transfers", "Transfers at the same time",
        "How many files upload or download at once. More can be faster on good connections.",
        minimum=1, maximum=16, keywords=("parallel", "concurrency", "speed"),
    ),
    SettingField(
        "file_browser.local_view", "file_browser", ("local_view",), "choice", "details", "files", "Local pane",
        "How your computer's files are shown.",
        choices=(("details", "Details list"), ("tree", "Folder tree")),
    ),
    SettingField(
        "file_browser.remote_view", "file_browser", ("remote_view",), "choice", "details", "files", "Server pane",
        "How the server's files are shown.",
        choices=(("details", "Details list"), ("tree", "Folder tree")),
    ),
    SettingField(
        "terminal.default_new_target", "terminal", ("default_new_target",), "choice", "active_remote", "terminal",
        "New terminal opens on", "Where a new terminal tab starts.",
        choices=(("active_remote", "The connected server"), ("local", "This computer")),
    ),
    SettingField(
        "terminal.font_size", "terminal", ("font_size",), "int", 13, "terminal", "Font size",
        "Text size in terminal tabs, in points.", minimum=8, maximum=40,
    ),
    SettingField(
        "terminal.scrollback", "terminal", ("scrollback",), "int", 5000, "terminal", "Scrollback lines",
        "How many lines each terminal keeps so you can scroll back.", minimum=500, maximum=50000,
    ),
    SettingField(
        "terminal.local_shell_path", "terminal", ("local_shell_path",), "text", "", "terminal", "Local shell",
        "Program for local terminals. Leave empty to use your default shell.",
        placeholder="powershell.exe, pwsh.exe or /bin/bash",
    ),
    SettingField(
        "tools.rsync_path", "tools", ("rsync_path",), "text", "rsync", "tools", "rsync program",
        "Used for faster server-to-server copies when the server supports it.", placeholder="rsync",
    ),
    SettingField(
        "tools.rclone_path", "tools", ("rclone_path",), "text", "rclone", "tools", "rclone program",
        "Path to rclone, for cloud storage remotes.", placeholder="rclone",
    ),
)
FIELDS_BY_ID = {f.id: f for f in FIELDS}


class SettingError(ValueError):
    pass


def coerce(spec: SettingField, value: Any) -> Any:
    if spec.kind == "choice":
        allowed = {key for key, _label in spec.choices}
        if value not in allowed:
            raise SettingError(f"{spec.label}: choose one of the listed options.")
        return value
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise SettingError(f"{spec.label}: turn it on or off.")
        return value
    if spec.kind == "int":
        if isinstance(value, bool):
            raise SettingError(f"{spec.label}: enter a whole number.")
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise SettingError(f"{spec.label}: enter a whole number.") from exc
        if (spec.minimum is not None and number < spec.minimum) or (spec.maximum is not None and number > spec.maximum):
            raise SettingError(f"{spec.label}: use a number from {spec.minimum} to {spec.maximum}.")
        return number
    if spec.kind == "text":
        if not isinstance(value, str):
            raise SettingError(f"{spec.label}: enter text.")
        text = value.strip()
        if len(text) > MAX_TEXT or any(ch in text for ch in ("\0", "\n", "\r")):
            raise SettingError(f"{spec.label}: use a single line of up to {MAX_TEXT} characters.")
        return text
    raise SettingError(f"Unknown setting type: {spec.kind}")


class SettingsStore:
    def __init__(self, app_data: AppDataService) -> None:
        self.app_data = app_data

    def _read_row(self, row: str) -> Any:
        with self.app_data.session_factory() as session:
            stored = self.app_data.settings(session).get(row)
        return stored.get("value") if isinstance(stored, dict) else None

    def get(self, field_id: str) -> Any:
        spec = FIELDS_BY_ID[field_id]
        value = self._read_row(spec.row)
        for part in spec.path:
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            return spec.default
        try:
            return coerce(spec, value)
        except SettingError:
            return spec.default

    def values(self) -> dict[str, Any]:
        return {spec.id: self.get(spec.id) for spec in FIELDS}

    def set(self, field_id: str, value: Any) -> Any:
        spec = FIELDS_BY_ID.get(field_id)
        if spec is None:
            raise SettingError("Unknown setting.")
        clean = coerce(spec, value)
        with self.app_data.session_factory() as session:
            repo = self.app_data.settings(session)
            stored = repo.get(spec.row)
            current = stored.get("value") if isinstance(stored, dict) else None
            if spec.path:
                row_value = dict(current) if isinstance(current, dict) else {}
                target = row_value
                for part in spec.path[:-1]:
                    nested = target.get(part)
                    target[part] = dict(nested) if isinstance(nested, dict) else {}
                    target = target[part]
                target[spec.path[-1]] = clean
            else:
                row_value = clean
            repo.set(spec.row, {"value": row_value})
            session.commit()
        return clean


def schema() -> dict[str, Any]:
    return {
        "groups": [{"id": gid, "label": label} for gid, label in GROUPS],
        "fields": [
            {
                "id": f.id, "group": f.group, "kind": f.kind, "label": f.label, "description": f.description,
                "default": f.default, "choices": [{"value": v, "label": lbl} for v, lbl in f.choices],
                "min": f.minimum, "max": f.maximum, "placeholder": f.placeholder, "keywords": list(f.keywords),
            }
            for f in FIELDS
        ],
    }
