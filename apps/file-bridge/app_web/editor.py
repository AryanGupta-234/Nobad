"""Editor tabs for the web UI: server files through RemoteEditManager, local files directly.

* Server files are downloaded into a private temp workspace (SecureTempWorkspace, 0700), and saving refuses when the
  file changed on the server since it was opened (RemoteEditManager raises; the page offers Compare, Overwrite or
  Reload). A backup copy is made on the server before saving, as in the classic window.
* Local files: the same 5 MB / binary limits, an atomic write (temp file + replace), and the same "changed since
  opened" check using the file's modification time.
* The text the user edits is never logged."""
from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app_web.files import FileError, run_sync
from editor.encoding import detect_encoding, is_probably_binary
from editor.remote_edit_manager import MAX_INLINE_EDIT_BYTES, RemoteEditManager
from editor.syntax import language_for_path
from file_ops.temp_workspace import SecureTempWorkspace
from security.secret_scanner import is_sensitive_path

MAX_TABS = 30
MAX_SAVE_CHARS = 20 * 1024 * 1024


@dataclass
class EditorTab:
    id: str
    side: str                      # "remote" | "local"
    path: str
    encoding: str
    language: str
    profile_id: str | None = None
    session: Any = None            # editor.editor_session.EditorSession (remote)
    manager: Any = None            # RemoteEditManager (remote)
    mtime_ns: int | None = None    # local
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "side": self.side, "path": self.path, "name": self.name, "language": self.language,
                "encoding": self.encoding, "warnings": self.warnings}


class EditorService:
    def __init__(self) -> None:
        self.tabs: dict[str, EditorTab] = {}
        self._workspace: SecureTempWorkspace | None = None

    def workspace(self) -> SecureTempWorkspace:
        if self._workspace is None:
            self._workspace = SecureTempWorkspace(prefix="nbfb-edit-")
        return self._workspace

    def list(self) -> list[dict[str, Any]]:
        return [t.summary() for t in self.tabs.values()]

    def get(self, tab_id: Any) -> EditorTab:
        tab = self.tabs.get(tab_id) if isinstance(tab_id, str) else None
        if tab is None:
            raise FileError("That file is no longer open.")
        return tab

    # ---------------------------------------------------------------- open
    def open(self, side: str, path: Any, connection: Any = None) -> dict[str, Any]:
        if not isinstance(path, str) or not path or len(path) > 4096:
            raise FileError("Choose a file.")
        for tab in self.tabs.values():            # the same file twice: reuse its tab
            if tab.side == side and tab.path == path and (side == "local" or (connection and tab.profile_id == connection.profile.id)):
                return {**tab.summary(), "text": self._current_text(tab), "reused": True}
        if len(self.tabs) >= MAX_TABS:
            raise FileError(f"Close a file first (up to {MAX_TABS} at a time).")
        if side == "remote":
            return self._open_remote(path, connection)
        if side == "local":
            return self._open_local(path)
        raise FileError("Unknown file location.")

    def _open_remote(self, path: str, connection: Any) -> dict[str, Any]:
        if connection is None:
            raise FileError("Not connected to a server.")
        manager = RemoteEditManager(connection.file_operations(), self.workspace())
        result = run_sync(manager.open_remote_file(path))
        if not result.ok:
            raise FileError(result.message)
        session = result.data
        session.profile_id = connection.profile.id
        text = session.local_path.read_text(encoding=session.encoding)
        tab = EditorTab(uuid.uuid4().hex[:12], "remote", path, session.encoding,
                        language_for_path(path, text[:200], text[:2000]), connection.profile.id, session, manager,
                        warnings=list(result.warnings))
        self.tabs[tab.id] = tab
        return {**tab.summary(), "text": text}

    def _open_local(self, path: str) -> dict[str, Any]:
        target = Path(path)
        try:
            info = target.stat()
        except OSError as exc:
            raise FileError(f"Can't open {target}: {exc.strerror or exc}") from exc
        if not target.is_file():
            raise FileError(f"{target} isn't a file.")
        warnings = []
        if info.st_size > MAX_INLINE_EDIT_BYTES:
            warnings.append("Large-file warning: this file is over 5 MB.")
        if is_sensitive_path(path):
            warnings.append("Sensitive file warning: contents will not be written to logs.")
        if is_probably_binary(target):
            raise FileError("This file looks binary, so it can't be edited safely.")
        encoding = detect_encoding(target)
        try:
            text = target.read_text(encoding=encoding)
        except (OSError, UnicodeDecodeError) as exc:
            raise FileError(f"Couldn't read {target.name} as text: {exc}") from exc
        tab = EditorTab(uuid.uuid4().hex[:12], "local", str(target), encoding,
                        language_for_path(target.name, text[:200], text[:2000]), mtime_ns=info.st_mtime_ns, warnings=warnings)
        self.tabs[tab.id] = tab
        return {**tab.summary(), "text": text}

    def _current_text(self, tab: EditorTab) -> str:
        source = tab.session.local_path if tab.side == "remote" else Path(tab.path)
        return Path(source).read_text(encoding=tab.encoding)

    # ---------------------------------------------------------------- save / compare
    def _attach(self, tab: EditorTab, connection: Any) -> None:
        """A server tab stays open across a disconnect (no edits are lost); saving needs that server again."""
        if connection is None or connection.profile.id != tab.profile_id:
            raise FileError("Connect to the server this file came from to save it. Your changes stay in the tab.")
        tab.manager.remote_ops = connection.file_operations()

    def save(self, tab_id: Any, text: Any, *, force: bool = False, connection: Any = None) -> dict[str, Any]:
        tab = self.get(tab_id)
        if not isinstance(text, str) or len(text) > MAX_SAVE_CHARS:
            raise FileError("This file is too large to save from the editor.")
        if tab.side == "remote":
            self._attach(tab, connection)
            result = run_sync(tab.manager.save_remote_file(tab.session, text, force=force))
            if not result.ok:
                return {"saved": False, "conflict": "changed after opening" in result.message.lower(),
                        "message": result.message, "fix": result.suggested_fix}
            return {"saved": True, "message": "Saved to the server."}
        target = Path(tab.path)
        try:
            current = target.stat().st_mtime_ns
        except FileNotFoundError:
            current = None
        if not force and current is not None and tab.mtime_ns is not None and current != tab.mtime_ns:
            return {"saved": False, "conflict": True, "message": "This file changed on disk after you opened it.",
                    "fix": "Compare the versions, reload it, or overwrite intentionally."}
        _atomic_write(target, text, tab.encoding)
        tab.mtime_ns = target.stat().st_mtime_ns
        return {"saved": True, "message": "Saved."}

    def latest(self, tab_id: Any, connection: Any = None) -> dict[str, Any]:
        """The file as it is now (on the server or on disk), for Compare and Reload."""
        tab = self.get(tab_id)
        if tab.side == "remote":
            self._attach(tab, connection)
            result = run_sync(tab.manager.read_remote_text(tab.session))
            if not result.ok:
                raise FileError(result.message)
            return {"text": result.data["text"]}
        return {"text": Path(tab.path).read_text(encoding=tab.encoding)}

    def reloaded(self, tab_id: Any, connection: Any = None) -> dict[str, Any]:
        """Take the latest version as the new starting point (after Reload)."""
        tab = self.get(tab_id)
        latest = self.latest(tab_id, connection)
        if tab.side == "remote":
            stat = run_sync(tab.manager.remote_ops.stat(tab.path))
            if stat.ok:
                tab.session.remote_modified_at = stat.data.modified_at
            tab.session.local_path.write_text(latest["text"], encoding=tab.encoding)
        else:
            tab.mtime_ns = Path(tab.path).stat().st_mtime_ns
        return latest

    def close(self, tab_id: Any) -> None:
        tab = self.tabs.pop(tab_id, None) if isinstance(tab_id, str) else None
        if tab is not None and tab.side == "remote":
            try:
                Path(tab.session.local_path).unlink(missing_ok=True)
            except OSError:
                pass

    def shutdown(self) -> None:
        self.tabs.clear()
        if self._workspace is not None:
            self._workspace.cleanup()
            self._workspace = None


def _atomic_write(target: Path, text: str, encoding: str) -> None:
    fd, temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".nbfb-save", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        try:
            os.chmod(temp, target.stat().st_mode & 0o7777)
        except OSError:
            pass
        os.replace(temp, target)
    except Exception:
        Path(temp).unlink(missing_ok=True)
        raise
