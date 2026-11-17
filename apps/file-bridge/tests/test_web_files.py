"""Local side of the Files API: listing, new/rename/delete, and names the user types."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app_web.api import api_post
from app_web.context import AppContext
from app_web.files import FileError, check_new_name
from app_web.handlers import register_all

register_all()


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    return AppContext.create(tmp_path / "app.sqlite3")


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    (root / "docs").mkdir(parents=True)
    (root / "notes.md").write_text("hello", encoding="utf-8")
    (root / ".env").write_text("SECRET=1", encoding="utf-8")
    return root


def test_local_list_is_compact_and_hides_dotfiles_by_default(ctx, folder: Path) -> None:
    reply = api_post("fs.local.list", {"path": str(folder)}, ctx)
    assert reply["ok"]
    data = reply["data"]
    assert data["path"] == str(folder.resolve())
    assert data["parent"] == str(folder.resolve().parent)
    by_name = {row[0]: row for row in data["items"]}
    assert set(by_name) == {"docs", "notes.md"}
    assert by_name["docs"][1] == "d" and by_name["notes.md"][1] == "f" and by_name["notes.md"][2] == 5
    assert isinstance(by_name["notes.md"][3], int)

    hidden = api_post("fs.local.list", {"path": str(folder), "hidden": True}, ctx)["data"]
    assert ".env" in {row[0] for row in hidden["items"]}


def test_local_list_reports_missing_folders_plainly(ctx, tmp_path: Path) -> None:
    reply = api_post("fs.local.list", {"path": str(tmp_path / "nope")}, ctx)
    assert not reply["ok"] and "isn't a folder" in reply["error"]


def test_local_mkdir_rename_delete(ctx, folder: Path) -> None:
    assert api_post("fs.local.mkdir", {"folder": str(folder), "name": "build"}, ctx)["ok"]
    assert (folder / "build").is_dir()
    assert api_post("fs.local.rename", {"path": str(folder / "build"), "name": "dist"}, ctx)["ok"]
    assert (folder / "dist").is_dir() and not (folder / "build").exists()
    (folder / "dist" / "app.js").write_text("x", encoding="utf-8")
    assert api_post("fs.local.delete", {"path": str(folder / "dist"), "recursive": True}, ctx)["ok"]
    assert not (folder / "dist").exists()


@pytest.mark.parametrize("name", ["", "  ", ".", "..", "../up", "a/b", "a\\b", "x\0y", "n" * 300])
def test_typed_names_must_be_one_plain_component(name: str) -> None:
    with pytest.raises(FileError):
        check_new_name(name)


@pytest.mark.skipif(os.name != "nt", reason="Windows file name rules")
@pytest.mark.parametrize("name", ["a:b", "what?", "trailing.", "pipe|name"])
def test_windows_invalid_names_are_refused(name: str) -> None:
    with pytest.raises(FileError):
        check_new_name(name)


def test_a_new_folder_cannot_escape_its_parent(ctx, folder: Path, tmp_path: Path) -> None:
    reply = api_post("fs.local.mkdir", {"folder": str(folder), "name": "../outside"}, ctx)
    assert not reply["ok"]
    assert not (tmp_path / "outside").exists()


def test_remote_actions_need_a_connection(ctx) -> None:
    for name, body in (("fs.remote.list", {"path": "/"}), ("fs.remote.mkdir", {"folder": "/", "name": "x"}),
                       ("xfer.plan", {"direction": "upload", "items": ["a"], "dest": "/"})):
        reply = api_post(name, body, ctx)
        assert not reply["ok"] and "Not connected" in reply["error"]


def test_local_roots_include_home(ctx) -> None:
    data = api_post("fs.local.roots", {}, ctx)["data"]
    assert data["home"] == str(Path.home()) and data["places"][0]["label"] == "Home"


def test_drives_are_listed_with_labels(ctx) -> None:
    drives = api_post("fs.local.roots", {}, ctx)["data"]["drives"]
    assert drives and all(set(d) == {"label", "path"} and Path(d["path"]).exists() for d in drives)


def test_mounted_disks_are_offered_on_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app_web import files as files_mod

    media = tmp_path / "media"
    (media / "alex" / "USB-STICK").mkdir(parents=True)
    (tmp_path / "mnt" / "backup").mkdir(parents=True)
    monkeypatch.setattr(files_mod, "MOUNT_PARENTS", (str(media), str(tmp_path / "mnt"), str(tmp_path / "nope")))
    drives = files_mod._posix_drives(Path("/home/alex"))
    paths = [d["path"] for d in drives]
    assert paths[0] == "/"
    assert str(media / "alex" / "USB-STICK") in paths and str(tmp_path / "mnt" / "backup") in paths
