"""The data folder is private (issue #31): folder 0700, files 0600, no shared /tmp fallback."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

import storage.app_data as app_data_module
from core import diagnostics
from core.private_paths import (
    APP_DIR_NAME,
    PrivatePathError,
    app_data_dir,
    ensure_private_file,
    private_temp_dir,
)
from security.known_hosts import default_known_hosts_path
from storage.app_data import AppDataService
from storage.database import init_database

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits; Windows uses the profile ACL")


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@posix_only
def test_data_folder_is_created_0700_and_an_existing_one_is_tightened(home: Path) -> None:
    folder = home / APP_DIR_NAME
    folder.mkdir(mode=0o755)
    os.chmod(folder, 0o755)

    assert app_data_dir() == folder
    assert _mode(folder) == 0o700


@posix_only
def test_default_database_is_0600_inside_a_0700_folder(home: Path) -> None:
    init_database()

    assert _mode(home / APP_DIR_NAME) == 0o700
    assert _mode(home / APP_DIR_NAME / "app.sqlite3") == 0o600


@posix_only
def test_an_existing_world_readable_database_is_tightened(tmp_path: Path) -> None:
    db = tmp_path / "app.sqlite3"
    db.write_bytes(b"")
    os.chmod(db, 0o644)

    init_database(db)

    assert _mode(db) == 0o600


@posix_only
def test_known_hosts_and_diagnostics_are_private(home: Path) -> None:
    known_hosts = default_known_hosts_path()
    folder = diagnostics.diagnostics_dir()

    assert _mode(known_hosts) == 0o600
    assert folder == home / APP_DIR_NAME / "diagnostics"
    assert _mode(folder) == 0o700


@posix_only
def test_a_symlinked_data_folder_is_refused(home: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "attacker-controlled"
    elsewhere.mkdir()
    (home / APP_DIR_NAME).symlink_to(elsewhere)

    with pytest.raises(PrivatePathError):
        app_data_dir()


@posix_only
def test_a_symlinked_database_file_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "somewhere-else"
    target.write_bytes(b"")
    link = tmp_path / "app.sqlite3"
    link.symlink_to(target)

    with pytest.raises(PrivatePathError):
        ensure_private_file(link)


@posix_only
def test_private_temp_dir_is_0700() -> None:
    folder = private_temp_dir("test")
    try:
        assert _mode(folder) == 0o700
    finally:
        folder.rmdir()


def test_fallback_is_a_fresh_private_folder_not_shared_tmp(monkeypatch: pytest.MonkeyPatch) -> None:
    real_init = app_data_module.init_database
    calls: list[object] = []

    def init_that_fails_first(path=None):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError("data folder is read-only")
        return real_init(path)

    monkeypatch.setattr(app_data_module, "init_database", init_that_fails_first)

    service = AppDataService.create()

    fallback = Path(calls[1])
    assert fallback.parent.name.startswith("nobad-file-bridge-data-")
    assert fallback.parent != Path(tempfile.gettempdir()) / "remote-file-manager"
    assert service.storage_warning and "won't be kept" in service.storage_warning
    assert "data folder is read-only" in service.storage_warning


def test_normal_start_has_no_storage_warning(tmp_path: Path) -> None:
    assert AppDataService.create(tmp_path / "app.sqlite3").storage_warning is None


def test_in_memory_database_creates_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    AppDataService.create(":memory:")

    assert not (tmp_path / ":memory:").exists()
