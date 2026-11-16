"""File listings and file operations for the web UI's dual-pane browser.

Listings are sent compactly (one small list per entry) so folders with 100,000+ files stay quick to transfer and
render. Names typed by the user for new files and folders must be one plain path component; names that came from a
server were already checked by the listing layer (file_ops/safety.py)."""
from __future__ import annotations

import os
import posixpath
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from core.async_runtime import AsyncRuntime
from core.result import OperationResult
from file_ops.base import FileItem, FileKind
from file_ops.local_ops import LocalFileOperations
from file_ops.metadata import local_file_item
from file_ops.safety import is_unsafe_entry_name

OP_TIMEOUT = 120.0
KINDS = {FileKind.DIRECTORY: "d", FileKind.FILE: "f", FileKind.SYMLINK: "l", FileKind.OTHER: "o"}
local_ops = LocalFileOperations()


class FileError(ValueError):
    pass


def run_sync(coro: Coroutine[Any, Any, Any], timeout: float = OP_TIMEOUT) -> Any:
    """Run a backend coroutine on the shared runtime from an HTTP handler thread."""
    future = AsyncRuntime.instance().submit(coro)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        raise FileError("The server took too long to answer. Try again.") from None


def check_new_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise FileError("Enter a name.")
    clean = name.strip()
    if is_unsafe_entry_name(clean) or len(clean) > 255 or any(ord(c) < 32 for c in clean):
        raise FileError("Use a name without / or \\, up to 255 characters.")
    if os.name == "nt" and (any(c in clean for c in '<>:"|?*') or clean.endswith((".", " "))):
        raise FileError('Windows names can\'t contain < > : " | ? * or end with a dot or space.')
    return clean


def compact(item: FileItem) -> list[Any]:
    """[name, kind, size, modified epoch seconds, permissions]"""
    modified = int(item.modified_at.timestamp()) if item.modified_at else None
    return [item.name, KINDS.get(item.kind, "o"), item.size, modified, item.permissions]


def explain(result: OperationResult) -> str:
    """The message plus the server's own reason (last line of the technical details), so errors say why."""
    reason = (result.technical_details or "").strip().splitlines()[-1:] or [""]
    detail = reason[0].split(": ", 1)[-1].strip()[:200]
    return f"{result.message} {detail}".strip() if detail and detail not in result.message else result.message


def _listing(path: str, parent: str | None, result: OperationResult) -> dict[str, Any]:
    if not result.ok:
        raise FileError(explain(result))
    items = result.data or []
    return {"path": path, "parent": parent, "items": [compact(i) for i in items], "warnings": list(result.warnings)}


# ---------------------------------------------------------------- local
def local_roots() -> dict[str, Any]:
    home = Path.home()
    places = [{"label": "Home", "path": str(home)}]
    for label in ("Desktop", "Documents", "Downloads"):
        folder = home / label
        if folder.is_dir():
            places.append({"label": label, "path": str(folder)})
    drives = list(getattr(os, "listdrives", lambda: [])()) if os.name == "nt" else ["/"]
    return {"home": str(home), "places": places, "drives": drives, "sep": os.sep}


def local_list(path: Any, *, hidden: bool = False) -> dict[str, Any]:
    target = Path(str(path or Path.home())).expanduser()
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise FileError(f"Can't open {target}: {exc}") from exc
    if not resolved.is_dir():
        raise FileError(f"{resolved} isn't a folder.")
    parent = str(resolved.parent) if resolved.parent != resolved else None
    # Listed right here on the request thread, not on the shared asyncio loop: the local pane must stay quick
    # even while a slow server listing or a big transfer keeps that loop busy.
    items: list[list[Any]] = []
    skipped = 0
    try:
        with os.scandir(resolved) as entries:
            for entry in entries:
                if not hidden and entry.name.startswith("."):
                    continue
                try:
                    items.append(compact(local_file_item(Path(entry.path))))
                except OSError:
                    skipped += 1
    except OSError as exc:
        raise FileError(f"Can't open {resolved}: {exc.strerror or exc}") from exc
    warnings = [f"{skipped} item(s) couldn't be read and are not shown."] if skipped else []
    return {"path": str(resolved), "parent": parent, "items": items, "warnings": warnings}


def local_child(folder: Any, name: Any) -> Path:
    return Path(str(folder)) / check_new_name(name)


def local_op(op: str, body: dict[str, Any]) -> OperationResult:
    if op == "mkdir":
        return run_sync(local_ops.create_folder(local_child(body.get("folder"), body.get("name"))))
    if op == "rename":
        source = Path(str(body.get("path")))
        return run_sync(local_ops.rename(source, source.parent / check_new_name(body.get("name"))))
    if op == "delete":
        return run_sync(local_ops.delete(Path(str(body.get("path"))), recursive=bool(body.get("recursive"))))
    raise FileError("Unknown action.")


# ---------------------------------------------------------------- remote
def remote_parent(path: str) -> str | None:
    if path in {"", ".", "/"}:
        return None
    parent = posixpath.dirname(path.rstrip("/")) or "/"
    return parent if parent != path else None


def remote_list(connection: Any, path: Any, *, hidden: bool = False) -> dict[str, Any]:
    if connection is None:
        raise FileError("Not connected to a server.")
    folder = str(path or connection.profile.default_remote_path or ".")
    ops = connection.file_operations()
    if folder == ".":
        resolved = _remote_realpath(connection)
        folder = resolved or folder
    return _listing(folder, remote_parent(folder), run_sync(ops.list_dir(folder, show_hidden=hidden)))


def _remote_realpath(connection: Any) -> str | None:
    """Absolute path of the server's start folder, so breadcrumbs and Up work (SFTP only)."""
    sftp = getattr(connection, "sftp_client", None)
    realpath = getattr(sftp, "realpath", None)
    if realpath is None:
        return None
    try:
        value = run_sync(realpath("."), timeout=15)
        return value.decode() if isinstance(value, bytes) else str(value)
    except Exception:
        return None


def remote_op(connection: Any, op: str, body: dict[str, Any]) -> OperationResult:
    if connection is None:
        raise FileError("Not connected to a server.")
    ops = connection.file_operations()
    if op == "mkdir":
        return run_sync(ops.create_folder(posixpath.join(str(body.get("folder")), check_new_name(body.get("name")))))
    if op == "rename":
        source = str(body.get("path"))
        return run_sync(ops.rename(source, posixpath.join(posixpath.dirname(source), check_new_name(body.get("name")))))
    if op == "delete":
        return run_sync(ops.delete(str(body.get("path")), recursive=bool(body.get("recursive"))))
    raise FileError("Unknown action.")
