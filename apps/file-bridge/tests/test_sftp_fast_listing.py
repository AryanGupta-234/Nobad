from __future__ import annotations

import asyncio
import stat
from dataclasses import dataclass

from file_ops.sftp_ops import SFTPFileOperations


@dataclass
class FakeAttrs:
    permissions: int
    size: int
    mtime: int
    uid: int = 1000
    gid: int = 1000


@dataclass
class FakeEntry:
    filename: str
    attrs: FakeAttrs


class FakeSFTP:
    def __init__(self) -> None:
        self.folders: set[str] = set()

    async def scandir(self, path="."):
        yield FakeEntry("folder", FakeAttrs(stat.S_IFDIR | 0o755, 0, 1))
        yield FakeEntry("file.txt", FakeAttrs(stat.S_IFREG | 0o644, 12, 1))

    async def mkdir(self, path):
        self.folders.add(path)

    async def stat(self, path):
        if path in self.folders:
            return FakeAttrs(stat.S_IFDIR | 0o755, 0, 1)
        raise FileNotFoundError(path)


def test_sftp_list_dir_uses_scandir_attrs() -> None:
    result = asyncio.run(SFTPFileOperations(FakeSFTP()).list_dir("."))

    assert result.ok
    assert [item.name for item in result.data] == ["folder", "file.txt"]
    assert result.data[0].is_dir
    assert result.data[1].size == 12


def test_sftp_ensure_folder_creates_parent_tree() -> None:
    fake = FakeSFTP()

    result = asyncio.run(SFTPFileOperations(fake).ensure_folder("/var/www/site"))

    assert result.ok
    assert fake.folders == {"/var", "/var/www", "/var/www/site"}
