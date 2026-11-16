from __future__ import annotations

import os
import posixpath
from pathlib import Path

from core.exceptions import UnsafePathError

PROTECTED_REMOTE_PATHS = {
    "/",
    "/home",
    "/var",
    "/etc",
    "/usr",
    "/bin",
    "/root",
    "/opt",
    "/srv",
}

PROTECTED_NAMES = {"public_html"}


def normalize_remote_path(path: str) -> str:
    if not path:
        return "."
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if path.startswith("/") and not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def is_protected_remote_path(path: str, configured_protected_paths: set[str] | None = None) -> bool:
    normalized = normalize_remote_path(path)
    protected = set(PROTECTED_REMOTE_PATHS)
    if configured_protected_paths:
        protected.update(normalize_remote_path(item) for item in configured_protected_paths)
    if normalized in protected:
        return True
    return posixpath.basename(normalized) in PROTECTED_NAMES


def ensure_not_protected(path: str, *, configured_protected_paths: set[str] | None = None) -> None:
    if is_protected_remote_path(path, configured_protected_paths):
        raise UnsafePathError(f"Refusing dangerous operation on protected path: {path}")


DOT_ENTRIES = {".", ".."}


def is_unsafe_entry_name(name: str) -> bool:
    """True when a name from a directory listing is not exactly one plain path component.

    Remote servers are untrusted: a listing can contain ``.``/``..`` (SFTP readdir always does) or a hostile name such
    as ``../../x``, ``..\\x`` or ``a/b`` that would escape the destination once joined into a local path."""
    return not name or name in DOT_ENTRIES or any(ch in name for ch in ("/", "\\", "\0"))


def ensure_safe_entry_name(name: str) -> str:
    if is_unsafe_entry_name(name):
        raise UnsafePathError(f"Refusing unsafe name from the server: {name!r}")
    return name


def skipped_names_warning(skipped: list[str]) -> list[str]:
    """One warning for listing entries hidden because their names are unsafe (kept short; names are repr()'d)."""
    if not skipped:
        return []
    shown = ", ".join(repr(name) for name in skipped[:5])
    more = f" and {len(skipped) - 5} more" if len(skipped) > 5 else ""
    return [f"Hid {len(skipped)} item(s) with unsafe names from the server: {shown}{more}."]


def is_path_traversal(member_name: str) -> bool:
    if "\0" in member_name:
        return True
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    return any(part == ".." for part in parts)


def safe_destination(root: Path, member_name: str) -> Path:
    """Local path for ``member_name`` inside ``root``; raises UnsafePathError if it would land anywhere else."""
    if is_path_traversal(member_name):
        raise UnsafePathError(f"Archive member escapes destination: {member_name}")
    root_resolved = root.resolve()
    target = (root_resolved / member_name).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePathError(f"Archive member escapes destination: {member_name}") from exc
    return target


def is_hidden_overwrite(member_name: str, existing_paths: set[str] | None = None) -> bool:
    if existing_paths is None:
        return False
    normalized = os.path.normpath(member_name)
    return normalized in {os.path.normpath(item) for item in existing_paths}

