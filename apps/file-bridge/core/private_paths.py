"""Private on-disk locations for NOBAD File Bridge data (issue #31).

The data folder holds the encrypted vault, saved profiles, logs, known_hosts and deployment configs. On POSIX it is
created 0700 and its files 0600, existing ones are tightened, and a folder that is a symlink or belongs to another
user is refused. There is no shared /tmp fallback: if the real folder can't be used, callers get a fresh private
``tempfile.mkdtemp()`` folder (0700, owned by us), and must tell the user that data won't be kept.

Windows: the folder lives in the user's profile, whose ACL already limits it to that user; chmod only toggles the
read-only bit there, so only the creation steps apply."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

# The on-disk name stays "remote-file-manager" on purpose so existing users keep their data (see the rename, #28).
APP_DIR_NAME = ".remote-file-manager"
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_POSIX = os.name == "posix"


class PrivatePathError(OSError):
    """The data location exists but isn't safe to use (symlink, owned by someone else, not a folder/file)."""


def app_data_dir(home: Path | None = None) -> Path:
    """``~/.remote-file-manager``, created private if missing and tightened if it already exists."""
    return ensure_private_dir((home or Path.home()) / APP_DIR_NAME)


def ensure_private_dir(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir(mode=PRIVATE_DIR_MODE)
    except FileExistsError:
        pass
    if _POSIX:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise PrivatePathError(f"Refusing to use {path}: it is a symbolic link.")
        if not stat.S_ISDIR(info.st_mode):
            raise PrivatePathError(f"Refusing to use {path}: it is not a folder.")
        if info.st_uid != os.getuid():
            raise PrivatePathError(f"Refusing to use {path}: it belongs to another user.")
        if stat.S_IMODE(info.st_mode) != PRIVATE_DIR_MODE:
            os.chmod(path, PRIVATE_DIR_MODE)
    return path


def ensure_private_file(path: Path) -> Path:
    """Create ``path`` 0600 if missing (never through a symlink) and tighten it if it already exists."""
    path = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags, PRIVATE_FILE_MODE)
    except OSError as exc:
        if _POSIX and os.path.islink(path):
            raise PrivatePathError(f"Refusing to use {path}: it is a symbolic link.") from exc
        raise
    try:
        if _POSIX:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise PrivatePathError(f"Refusing to use {path}: it is not a regular file.")
            if info.st_uid != os.getuid():
                raise PrivatePathError(f"Refusing to use {path}: it belongs to another user.")
            if stat.S_IMODE(info.st_mode) != PRIVATE_FILE_MODE:
                os.fchmod(fd, PRIVATE_FILE_MODE)
    finally:
        os.close(fd)
    return path


def private_temp_dir(purpose: str) -> Path:
    """A new folder only we can read (``mkdtemp`` creates it 0700), for when the real data folder is unusable."""
    return Path(tempfile.mkdtemp(prefix=f"nobad-file-bridge-{purpose}-"))
