"""Remote servers are untrusted: names in a listing must never escape the local download folder (issue #29).

The fake servers below return what a hostile or buggy server could send: ``.``/``..`` (every SFTP readdir does),
traversal names, backslash names, names with a slash, a NUL, and symlinks that point outside the folder."""
from __future__ import annotations

import asyncio
import posixpath
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from core.exceptions import UnsafePathError
from file_ops.base import FileItem, FileKind
from file_ops.ftp_ops import FTPFileOperations
from file_ops.safety import is_unsafe_entry_name, safe_destination
from file_ops.sftp_ops import SFTPFileOperations
from core.result import OperationResult
from transfers.transfer_manager import TransferManager

HOSTILE_NAMES = ["../escape.txt", "..\\escape.txt", "a/b.txt", "/etc/escape.txt", "bad\0name"]


# ---------------------------------------------------------------- safety helpers
@pytest.mark.parametrize("name", ["", ".", "..", *HOSTILE_NAMES])
def test_unsafe_entry_names_are_detected(name: str) -> None:
    assert is_unsafe_entry_name(name)


@pytest.mark.parametrize("name", ["file.txt", ".env", "..hidden", "name with spaces", "ünïcode", "a..b"])
def test_plain_entry_names_are_allowed(name: str) -> None:
    assert not is_unsafe_entry_name(name)


@pytest.mark.parametrize("member", ["../x", "..\\x", "a/../../x", "/abs/x", "x\0y"])
def test_safe_destination_refuses_escapes(tmp_path: Path, member: str) -> None:
    with pytest.raises(UnsafePathError):
        safe_destination(tmp_path, member)


# ---------------------------------------------------------------- fake SFTP server
@dataclass
class Attrs:
    permissions: int
    size: int = 0
    mtime: int = 86_400 * 400


@dataclass
class Entry:
    filename: str
    attrs: Attrs


DIR = stat.S_IFDIR | 0o755
FILE = stat.S_IFREG | 0o644
LINK = stat.S_IFLNK | 0o777


class FakeSFTP:
    """Paths map to ("dir", [names]), ("file", bytes) or ("link", target). Child paths are posixpath.join()ed
    exactly as the client builds them, so a hostile name resolves to whatever the server wants it to."""

    def __init__(self, tree: dict[str, tuple], *, dot_entries: bool = True) -> None:
        self.tree = tree
        self.dots = [".", ".."] if dot_entries else []
        self.removed: list[str] = []
        self.rmdirs: list[str] = []

    def _node(self, path: str, follow: bool) -> tuple:
        node = self.tree.get(path)
        if node is None:
            raise FileNotFoundError(path)
        if follow and node[0] == "link":
            return self._node(node[1], follow)
        return node

    def _attrs(self, node: tuple) -> Attrs:
        kind = node[0]
        if kind == "dir":
            return Attrs(DIR)
        if kind == "link":
            return Attrs(LINK)
        return Attrs(FILE, size=len(node[1]))

    async def scandir(self, path="."):
        for name in [*self.dots, *self._node(path, True)[1]]:
            child = posixpath.join(path, name)
            node = self.tree.get(child, ("dir", []))
            yield Entry(name, self._attrs(node))

    async def listdir(self, path="."):
        return [*self.dots, *self._node(path, True)[1]]

    async def stat(self, path):
        if path.endswith("/.") or path.endswith("/.."):
            return Attrs(DIR)            # a real server answers "." and ".." as directories
        return self._attrs(self._node(path, True))

    async def lstat(self, path):
        if path.endswith("/.") or path.endswith("/.."):
            return Attrs(DIR)
        return self._attrs(self._node(path, False))

    async def get(self, remote_path, local_path, progress_handler=None):
        Path(local_path).write_bytes(self._node(remote_path, True)[1])

    async def remove(self, path):
        self.removed.append(path)

    async def rmdir(self, path):
        self.rmdirs.append(path)


def _hostile_sftp_tree(name: str) -> FakeSFTP:
    # No dot entries here: some servers omit them, and the old code only "survived" a hostile name by recursing
    # into "." until it crashed.
    return FakeSFTP(dot_entries=False, tree={
        "/srv/site": ("dir", ["index.html", name]),
        "/srv/site/index.html": ("file", b"ok"),
        posixpath.join("/srv/site", name): ("file", b"pwned"),
    })


def test_sftp_listing_hides_dot_entries_and_hostile_names() -> None:
    fake = FakeSFTP({
        "/srv/site": ("dir", ["index.html", ".env", *HOSTILE_NAMES]),
        "/srv/site/index.html": ("file", b"ok"),
        "/srv/site/.env": ("file", b"x"),
    })

    result = asyncio.run(SFTPFileOperations(fake).list_dir("/srv/site", show_hidden=True))

    assert result.ok
    assert [item.name for item in result.data] == [".env", "index.html"]
    assert result.warnings and "5 item(s) with unsafe names" in result.warnings[0]


@pytest.mark.parametrize("name", HOSTILE_NAMES[:4])
def test_sftp_folder_download_refuses_hostile_names(tmp_path: Path, name: str) -> None:
    target = tmp_path / "downloads" / "site"

    result = asyncio.run(SFTPFileOperations(_hostile_sftp_tree(name)).download_folder_recursive("/srv/site", target))

    assert not result.ok
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "downloads" / "escape.txt").exists()
    assert not list(tmp_path.rglob("escape.txt"))


def test_sftp_folder_download_skips_dot_entries_and_symlinked_folders(tmp_path: Path) -> None:
    fake = FakeSFTP({
        "/srv/site": ("dir", ["index.html", "assets", "loop"]),
        "/srv/site/index.html": ("file", b"ok"),
        "/srv/site/assets": ("dir", ["app.js"]),
        "/srv/site/assets/app.js": ("file", b"js"),
        "/srv/site/loop": ("link", "/srv/site"),          # would recurse forever if followed
    })
    target = tmp_path / "site"

    result = asyncio.run(SFTPFileOperations(fake).download_folder_recursive("/srv/site", target))

    assert result.ok, result.message
    assert (target / "index.html").read_bytes() == b"ok"
    assert (target / "assets" / "app.js").read_bytes() == b"js"
    assert not (target / "loop").exists()


def test_sftp_recursive_delete_never_follows_dot_entries_or_symlinks() -> None:
    fake = FakeSFTP({
        "/srv/site/old": ("dir", ["a.txt", "home-link"]),
        "/srv/site/old/a.txt": ("file", b"a"),
        "/srv/site/old/home-link": ("link", "/home/user"),
        "/home/user": ("dir", ["precious.txt"]),
        "/home/user/precious.txt": ("file", b"keep"),
    })

    result = asyncio.run(SFTPFileOperations(fake).delete("/srv/site/old", recursive=True))

    assert result.ok, result.message
    assert sorted(fake.removed) == ["/srv/site/old/a.txt", "/srv/site/old/home-link"]
    assert fake.rmdirs == ["/srv/site/old"]
    assert not any(path.startswith("/home/user") for path in fake.removed + fake.rmdirs)


def test_sftp_recursive_delete_of_a_symlink_removes_only_the_link() -> None:
    fake = FakeSFTP({
        "/srv/site/shared": ("link", "/home/user"),
        "/home/user": ("dir", ["precious.txt"]),
        "/home/user/precious.txt": ("file", b"keep"),
    })

    result = asyncio.run(SFTPFileOperations(fake).delete("/srv/site/shared", recursive=True))

    assert result.ok, result.message
    assert fake.removed == ["/srv/site/shared"]
    assert fake.rmdirs == []


# ---------------------------------------------------------------- fake FTP server
class FakeStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def iter_by_block(self, size):
        yield self._data


class FakeFTP:
    """Mimics aioftp: list() yields PurePosixPath(folder) / <name the server sent>."""

    def __init__(self, folders: dict[str, list[str]], files: dict[str, bytes]) -> None:
        self.folders = folders
        self.files = files

    async def list(self, path):
        for name in self.folders.get(posixpath.normpath(path), []):
            child = PurePosixPath(path) / name
            yield child, {"type": "dir" if posixpath.normpath(str(child)) in self.folders else "file"}

    async def stat(self, path):
        normalized = posixpath.normpath(path)
        if normalized in self.folders:
            return {"type": "dir"}
        if normalized in self.files:
            return {"type": "file", "size": str(len(self.files[normalized]))}
        raise FileNotFoundError(path)

    def download_stream(self, path):
        return FakeStream(self.files[posixpath.normpath(path)])


def test_ftp_listing_hides_hostile_names() -> None:
    fake = FakeFTP({"/srv/site": ["index.html", "../escape.txt", "/etc/escape.txt", "a/b.txt", "..\\escape.txt"]},
                   {"/srv/site/index.html": b"ok"})

    result = asyncio.run(FTPFileOperations(fake).list_dir("/srv/site", show_hidden=True))

    assert result.ok
    assert [item.name for item in result.data] == ["index.html"]
    assert result.warnings and "4 item(s) with unsafe names" in result.warnings[0]


def test_ftp_folder_download_stays_inside_the_target(tmp_path: Path) -> None:
    fake = FakeFTP({"/srv/site": ["index.html", "../escape.txt", "assets"], "/srv/site/assets": ["app.js"]},
                   {"/srv/site/index.html": b"ok", "/srv/escape.txt": b"pwned", "/srv/site/assets/app.js": b"js"})
    target = tmp_path / "site"

    result = asyncio.run(FTPFileOperations(fake).download_folder_recursive("/srv/site", target))

    assert result.ok, result.message
    assert (target / "index.html").read_bytes() == b"ok"
    assert (target / "assets" / "app.js").read_bytes() == b"js"
    assert not list(tmp_path.rglob("escape.txt"))


# ---------------------------------------------------------------- transfer manager
class CraftedRemoteOps:
    """A remote adapter whose listing already contains an escaping path (defence in depth below the listing)."""

    async def list_dir(self, path, show_hidden=False):
        return OperationResult.success("listed", data=[
            FileItem(name="index.html", path="/srv/site/index.html", kind=FileKind.FILE, size=2),
            FileItem(name="escape.txt", path="/srv/site/../../escape.txt", kind=FileKind.FILE, size=5),
        ])


def test_transfer_manager_refuses_a_folder_download_that_would_escape(tmp_path: Path) -> None:
    manager = TransferManager()
    folder = FileItem(name="site", path="/srv/site", kind=FileKind.DIRECTORY)

    with pytest.raises(UnsafePathError):
        asyncio.run(manager.enqueue_download_folder(CraftedRemoteOps(), remote_item=folder, local_folder=tmp_path / "site"))

    assert manager.queue.queued() == []
