from __future__ import annotations

import io
import tarfile
from pathlib import Path

from file_ops.archive_ops import validate_archive_members


def test_tar_symlink_is_blocked(tmp_path: Path) -> None:
    archive = tmp_path / "links.tar"
    with tarfile.open(archive, "w") as handle:
        info = tarfile.TarInfo("safe-link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        handle.addfile(info, io.BytesIO())

    result = validate_archive_members(archive, tmp_path / "extract")

    assert not result.ok
    assert "links" in result.message.lower()
