from __future__ import annotations

from pathlib import Path

import pytest

from core.exceptions import UnsafePathError
from file_ops.safety import (
    ensure_not_protected,
    is_path_traversal,
    is_protected_remote_path,
    safe_destination,
)


def test_protected_remote_paths_are_detected() -> None:
    assert is_protected_remote_path("/")
    assert is_protected_remote_path("/etc")
    assert is_protected_remote_path("/home/site/public_html")
    assert not is_protected_remote_path("/home/site/public_html/assets")


def test_ensure_not_protected_raises() -> None:
    with pytest.raises(UnsafePathError):
        ensure_not_protected("/var")


def test_path_traversal_detection() -> None:
    assert is_path_traversal("../secret")
    assert is_path_traversal("/absolute/path")
    assert is_path_traversal("safe/../../secret")
    assert not is_path_traversal("safe/folder/file.txt")


def test_safe_destination_stays_under_root(tmp_path: Path) -> None:
    target = safe_destination(tmp_path, "safe/file.txt")
    assert target == tmp_path.resolve() / "safe" / "file.txt"
    with pytest.raises(UnsafePathError):
        safe_destination(tmp_path, "../escape.txt")

