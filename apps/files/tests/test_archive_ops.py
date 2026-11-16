from __future__ import annotations

import asyncio
import tarfile
import zipfile
from pathlib import Path

from file_ops.archive_models import ArchiveFormat, ArchiveOperationRequest
from file_ops.archive_ops import LocalArchiveOperations, archive_format_for_path, validate_archive_members


def test_unsupported_archive_returns_failure(tmp_path: Path) -> None:
    archive = tmp_path / "not-an-archive.bin"
    archive.write_bytes(b"hello")

    result = validate_archive_members(archive, tmp_path / "extract")

    assert not result.ok
    assert "inspect" in result.message.lower()


def test_local_archive_preview_zip_reports_members_and_size(tmp_path: Path) -> None:
    archive = tmp_path / "site.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("index.html", "hello")

    result = asyncio.run(LocalArchiveOperations().preview(archive, destination=tmp_path / "extract"))

    assert result.ok
    assert result.data.format == ArchiveFormat.ZIP
    assert result.data.member_names == ["index.html"]
    assert result.data.total_size == 5


def test_local_archive_create_and_extract_tar_gz(tmp_path: Path) -> None:
    source = tmp_path / "site"
    source.mkdir()
    (source / "index.html").write_text("hello", encoding="utf-8")
    archive = tmp_path / "site.tar.gz"
    destination = tmp_path / "extract"
    ops = LocalArchiveOperations()

    create = asyncio.run(
        ops.create(ArchiveOperationRequest(sources=[source], destination=archive, archive_format=ArchiveFormat.TAR_GZ))
    )
    extract = asyncio.run(ops.extract(archive, destination))

    assert create.ok
    assert extract.ok
    assert (destination / "site" / "index.html").read_text(encoding="utf-8") == "hello"


def test_local_archive_preview_tar_gz(tmp_path: Path) -> None:
    source = tmp_path / "file.txt"
    source.write_text("hello", encoding="utf-8")
    archive = tmp_path / "file.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="file.txt")

    result = asyncio.run(LocalArchiveOperations().preview(archive, destination=tmp_path / "extract"))

    assert result.ok
    assert result.data.format == ArchiveFormat.TAR_GZ
    assert result.data.member_names == ["file.txt"]


def test_local_folder_size(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("abc", encoding="utf-8")
    (folder / "b.txt").write_text("de", encoding="utf-8")

    result = asyncio.run(LocalArchiveOperations().calculate_folder_size(folder))

    assert result.ok
    assert result.data.size_bytes == 5


def test_archive_format_detection() -> None:
    assert archive_format_for_path("site.zip") == ArchiveFormat.ZIP
    assert archive_format_for_path("site.tar.gz") == ArchiveFormat.TAR_GZ
