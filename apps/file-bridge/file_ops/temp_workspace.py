from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


class SecureTempWorkspace:
    def __init__(self, prefix: str = "rfm-edit-") -> None:
        self._temp = tempfile.TemporaryDirectory(prefix=prefix)
        self.root = Path(self._temp.name)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    def path_for_remote(self, remote_path: str) -> Path:
        safe_name = remote_path.strip("/").replace("/", "__").replace("\\", "__") or "remote-file"
        return self.root / safe_name

    def cleanup(self) -> None:
        self._temp.cleanup()

    def __enter__(self) -> "SecureTempWorkspace":
        return self

    def __exit__(self, *_exc) -> None:  # type: ignore[no-untyped-def]
        self.cleanup()


def cleanup_temp_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)

