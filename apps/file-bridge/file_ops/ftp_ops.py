from __future__ import annotations

import hashlib
import posixpath
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from core.result import OperationResult, result_from_exception
from file_ops.base import FileItem, FileKind
from file_ops.remote import ProgressCallback
from file_ops.safety import ensure_not_protected


class FTPFileOperations:
    def __init__(self, client: Any, *, block_size: int = 256 * 1024) -> None:
        self._client = client
        self.block_size = block_size

    async def list_dir(self, path: str = ".", *, show_hidden: bool = False) -> OperationResult:
        try:
            items: list[FileItem] = []
            async for remote_path, info in self._client.list(path):
                name = PurePosixPath(str(remote_path)).name
                if name in {".", ".."} or (not show_hidden and name.startswith(".")):
                    continue
                items.append(self._item(str(remote_path), info))
            items.sort(key=lambda item: (not item.is_dir, item.name.lower()))
            return OperationResult.success("Remote directory listed.", data=items)
        except Exception as exc:
            return result_from_exception("Could not list remote directory.", exc, retryable=True)

    async def stat(self, path: str) -> OperationResult:
        try:
            info = await self._client.stat(path)
            return OperationResult.success("Remote metadata loaded.", data=self._item(path, info))
        except Exception as exc:
            return result_from_exception("Could not read remote metadata.", exc, retryable=True)

    async def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> OperationResult:
        source = Path(local_path)
        total = source.stat().st_size
        done = 0
        try:
            async with self._client.upload_stream(remote_path) as stream:
                with source.open("rb") as handle:
                    while True:
                        block = handle.read(self.block_size)
                        if not block:
                            break
                        await stream.write(block)
                        done += len(block)
                        if progress_callback:
                            progress_callback(str(source), remote_path, done, total)
            if progress_callback:
                progress_callback(str(source), remote_path, total, total)
            return OperationResult.success("File uploaded.", affected_paths=[str(source), remote_path])
        except Exception as exc:
            return result_from_exception("Could not upload file.", exc, retryable=True)

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> OperationResult:
        target = Path(local_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        stat_result = await self.stat(remote_path)
        total = stat_result.data.size if stat_result.ok and stat_result.data.size is not None else 0
        done = 0
        try:
            async with self._client.download_stream(remote_path) as stream:
                with target.open("wb") as handle:
                    async for block in stream.iter_by_block(self.block_size):
                        handle.write(block)
                        done += len(block)
                        if progress_callback:
                            progress_callback(remote_path, str(target), done, total)
            if progress_callback:
                progress_callback(remote_path, str(target), done, total or done)
            return OperationResult.success("File downloaded.", affected_paths=[remote_path, str(target)])
        except Exception as exc:
            return result_from_exception("Could not download file.", exc, retryable=True)

    async def download_folder_recursive(self, remote_path: str, local_folder: str | Path) -> OperationResult:
        try:
            await self._download_tree(remote_path, Path(local_folder))
            return OperationResult.success("Folder downloaded.", affected_paths=[remote_path, str(local_folder)])
        except Exception as exc:
            return result_from_exception("Could not download folder.", exc, retryable=True)

    async def create_file(self, remote_path: str) -> OperationResult:
        try:
            async with self._client.upload_stream(remote_path):
                pass
            return OperationResult.success("Remote file created.", affected_paths=[remote_path])
        except Exception as exc:
            return result_from_exception("Could not create remote file.", exc)

    async def create_folder(self, remote_path: str) -> OperationResult:
        try:
            await self._client.make_directory(remote_path)
            return OperationResult.success("Remote folder created.", affected_paths=[remote_path])
        except Exception as exc:
            return result_from_exception("Could not create remote folder.", exc)

    async def ensure_folder(self, remote_path: str) -> OperationResult:
        try:
            await self._client.make_directory(remote_path, parents=True)
            return OperationResult.success("Remote folder exists.", affected_paths=[remote_path])
        except Exception as exc:
            if await self._exists(remote_path):
                return OperationResult.success("Remote folder exists.", affected_paths=[remote_path])
            return result_from_exception("Could not create remote folder tree.", exc)

    async def rename(self, source: str, destination: str) -> OperationResult:
        try:
            await self._client.rename(source, destination)
            return OperationResult.success("Remote item renamed.", affected_paths=[source, destination])
        except Exception as exc:
            return result_from_exception("Could not rename remote item.", exc)

    async def delete(self, remote_path: str, *, recursive: bool = False) -> OperationResult:
        try:
            ensure_not_protected(remote_path)
            item = await self.stat(remote_path)
            if not item.ok:
                return item
            if item.data.is_dir:
                if recursive:
                    listed = await self.list_dir(remote_path, show_hidden=True)
                    if not listed.ok:
                        return listed
                    for child in listed.data:
                        deleted = await self.delete(child.path, recursive=True)
                        if not deleted.ok:
                            return deleted
                await self._client.remove_directory(remote_path)
            else:
                await self._client.remove_file(remote_path)
            return OperationResult.success("Remote item deleted.", affected_paths=[remote_path])
        except Exception as exc:
            return result_from_exception("Could not delete remote item.", exc)

    async def backup_file(self, remote_path: str, backup_path: str) -> OperationResult:
        with tempfile.TemporaryDirectory(prefix="rfm-ftp-backup-") as folder:
            local = Path(folder) / PurePosixPath(remote_path).name
            download = await self.download_file(remote_path, local)
            if not download.ok:
                return download
            return await self.upload_file(local, backup_path)

    async def calculate_checksum(self, remote_path: str, algorithm: str = "sha256") -> OperationResult:
        digest = hashlib.new(algorithm)
        try:
            async with self._client.download_stream(remote_path) as stream:
                async for block in stream.iter_by_block(self.block_size):
                    digest.update(block)
            return OperationResult.success(
                f"Remote {algorithm} checksum calculated.",
                data=digest.hexdigest(),
                affected_paths=[remote_path],
            )
        except Exception as exc:
            return result_from_exception("Could not calculate remote checksum.", exc, retryable=True)

    async def _download_tree(self, remote_path: str, local_path: Path) -> None:
        stat_result = await self.stat(remote_path)
        if not stat_result.ok:
            raise RuntimeError(stat_result.message)
        if stat_result.data.is_dir:
            local_path.mkdir(parents=True, exist_ok=True)
            listed = await self.list_dir(remote_path, show_hidden=True)
            if not listed.ok:
                raise RuntimeError(listed.message)
            for item in listed.data:
                await self._download_tree(item.path, local_path / item.name)
        else:
            result = await self.download_file(remote_path, local_path)
            if not result.ok:
                raise RuntimeError(result.message)

    async def _exists(self, path: str) -> bool:
        try:
            return bool(await self._client.exists(path))
        except Exception:
            return False

    def _item(self, path: str, info: dict[str, str]) -> FileItem:
        kind_value = str(info.get("type", "file")).lower()
        kind = FileKind.DIRECTORY if kind_value == "dir" else FileKind.SYMLINK if kind_value == "link" else FileKind.FILE
        size_value = info.get("size")
        modified = self._modified(info.get("modify"))
        normalized = posixpath.normpath(path)
        return FileItem(
            name=PurePosixPath(normalized).name,
            path=normalized,
            kind=kind,
            size=int(size_value) if size_value and kind == FileKind.FILE else None,
            modified_at=modified,
            permissions=info.get("unix.mode"),
            owner=info.get("unix.owner"),
            group=info.get("unix.group"),
        )

    def _modified(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
