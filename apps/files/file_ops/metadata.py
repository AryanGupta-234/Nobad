from __future__ import annotations

import mimetypes
import stat
from datetime import datetime
from pathlib import Path

from file_ops.base import FileItem, FileKind


def local_file_item(path: str | Path) -> FileItem:
    item = Path(path)
    info = item.lstat()
    if stat.S_ISDIR(info.st_mode):
        kind = FileKind.DIRECTORY
    elif stat.S_ISLNK(info.st_mode):
        kind = FileKind.SYMLINK
    elif stat.S_ISREG(info.st_mode):
        kind = FileKind.FILE
    else:
        kind = FileKind.OTHER
    return FileItem(
        name=item.name,
        path=str(item),
        kind=kind,
        size=info.st_size if kind == FileKind.FILE else None,
        modified_at=datetime.fromtimestamp(info.st_mtime).astimezone(),
        permissions=stat.filemode(info.st_mode),
        mime_type=mimetypes.guess_type(item.name)[0],
    )

