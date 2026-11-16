from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from core.result import OperationResult


ProgressCallback = Callable[[str, str, int, int], None]


@runtime_checkable
class RemoteFileOperations(Protocol):
    async def list_dir(self, path: str = ".", *, show_hidden: bool = False) -> OperationResult: ...

    async def stat(self, path: str) -> OperationResult: ...

    async def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> OperationResult: ...

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> OperationResult: ...

    async def download_folder_recursive(self, remote_path: str, local_folder: str | Path) -> OperationResult: ...

    async def create_file(self, remote_path: str) -> OperationResult: ...

    async def create_folder(self, remote_path: str) -> OperationResult: ...

    async def ensure_folder(self, remote_path: str) -> OperationResult: ...

    async def rename(self, source: str, destination: str) -> OperationResult: ...

    async def delete(self, remote_path: str, *, recursive: bool = False) -> OperationResult: ...

    async def backup_file(self, remote_path: str, backup_path: str) -> OperationResult: ...

    async def calculate_checksum(self, remote_path: str, algorithm: str = "sha256") -> OperationResult: ...
