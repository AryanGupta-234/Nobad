from __future__ import annotations

import zipfile
from pathlib import Path

from file_ops.archive_ops import validate_archive_members


def test_zip_slip_archive_is_blocked(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../evil.txt", "nope")

    result = validate_archive_members(archive, tmp_path / "extract")

    assert not result.ok
    assert "unsafe" in result.message.lower()


def test_safe_zip_validates(tmp_path: Path) -> None:
    archive = tmp_path / "good.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("folder/file.txt", "ok")

    result = validate_archive_members(archive, tmp_path / "extract")

    assert result.ok
    assert result.data == ["folder/file.txt"]

