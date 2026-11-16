from __future__ import annotations

import posixpath
import stat
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.result import OperationResult, result_from_exception
from file_ops.base import FileItem, FileKind
from file_ops.safety import ensure_not_protected


class SFTPFileOperations:
    def __init__(self, sftp: Any) -> None:
        self._sftp = sftp

    async def list_dir(self, path: str = ".", *, show_hidden: bool = False) -> OperationResult:
        try:
            items: list[FileItem] = []
            async for entry in self._sftp.scandir(path):
                name = self._decode_path(entry.filename)
                if not show_hidden and name.startswith("."):
                    continue
                full_path = posixpath.join(path, name) if path not in {"", "."} else name
                items.append(self._item_from_attrs(name, full_path, entry.attrs))
            items.sort(key=lambda item: (not item.is_dir, item.name.lower()))
            return OperationResult.success("Remote directory listed.", data=items)
        except Exception as exc:
            return result_from_exception("Could not list remote directory.", exc, retryable=True)

    async def stat(self, path: str) -> OperationResult:
        try:
            attrs = await self._sftp.stat(path)
            return OperationResult.success("Remote metadata loaded.", data=self._item_from_attrs(posixpath.basename(path), path, attrs))
        except Exception as exc:
            return result_from_exception("Could not read remote metadata.", exc, retryable=True)

    async def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        progress_callback: Callable[[str, str, int, int], None] | None = None,
    ) -> OperationResult:
        try:
            await self._sftp.put(str(local_path), remote_path, progress_handler=self._wrap_progress(progress_callback))
            return OperationResult.success("File uploaded.", affected_paths=[str(local_path), remote_path])
        except Exception as exc:
            return result_from_exception("Could not upload file.", exc, retryable=True)

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path,
        *,
        progress_callback: Callable[[str, str, int, int], None] | None = None,
    ) -> OperationResult:
        try:
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            await self._sftp.get(remote_path, str(local_path), progress_handler=self._wrap_progress(progress_callback))
            return OperationResult.success("File downloaded.", affected_paths=[remote_path, str(local_path)])
        except Exception as exc:
            return result_from_exception("Could not download file.", exc, retryable=True)

    async def download_folder_recursive(self, remote_path: str, local_folder: str | Path) -> OperationResult:
        local_root = Path(local_folder)
        try:
            await self._download_tree(remote_path, local_root)
            return OperationResult.success("Folder downloaded.", affected_paths=[remote_path, str(local_root)])
        except Exception as exc:
            return result_from_exception("Could not download folder.", exc, retryable=True)

    async def create_file(self, remote_path: str) -> OperationResult:
        try:
            async with self._sftp.open(remote_path, "x") as handle:
                await handle.write("")
            return OperationResult.success("Remote file created.", affected_paths=[remote_path])
        except Exception as exc:
            return result_from_exception("Could not create remote file.", exc)

    async def create_folder(self, remote_path: str) -> OperationResult:
        try:
            await self._sftp.mkdir(remote_path)
            return OperationResult.success("Remote folder created.", affected_paths=[remote_path])
        except Exception as exc:
            return result_from_exception("Could not create remote folder.", exc)

    async def ensure_folder(self, remote_path: str) -> OperationResult:
        normalized = remote_path.strip("/") if remote_path.startswith("/") else remote_path
        if normalized in {"", "."}:
            return OperationResult.success("Remote folder exists.", affected_paths=[remote_path])
        prefix = "/" if remote_path.startswith("/") else ""
        current = prefix
        try:
            for part in [part for part in normalized.split("/") if part and part != "."]:
                current = posixpath.join(current, part) if current else part
                try:
                    await self._sftp.mkdir(current)
                except Exception:
                    attrs = await self._sftp.stat(current)
                    if not self._is_dir(attrs):
                        return OperationResult.failure(f"Remote path exists but is not a folder: {current}")
            return OperationResult.success("Remote folder exists.", affected_paths=[remote_path])
        except Exception as exc:
            return result_from_exception("Could not create remote folder tree.", exc)

    async def rename(self, source: str, destination: str) -> OperationResult:
        try:
            await self._sftp.rename(source, destination)
            return OperationResult.success("Remote item renamed.", affected_paths=[source, destination])
        except Exception as exc:
            return result_from_exception("Could not rename remote item.", exc)

    async def delete(self, remote_path: str, *, recursive: bool = False) -> OperationResult:
        try:
            ensure_not_protected(remote_path)
            attrs = await self._sftp.stat(remote_path)
            if self._is_dir(attrs):
                if recursive:
                    await self._delete_tree(remote_path)
                else:
                    await self._sftp.rmdir(remote_path)
            else:
                await self._sftp.remove(remote_path)
            return OperationResult.success("Remote item deleted.", affected_paths=[remote_path])
        except Exception as exc:
            return result_from_exception("Could not delete remote item.", exc)

    async def backup_file(self, remote_path: str, backup_path: str) -> OperationResult:
        try:
            await self._sftp.copy(remote_path, backup_path)
            return OperationResult.success("Remote backup created.", affected_paths=[backup_path])
        except AttributeError:
            try:
                async with self._sftp.open(remote_path, "rb") as source:
                    data = await source.read()
                async with self._sftp.open(backup_path, "wb") as destination:
                    await destination.write(data)
                return OperationResult.success("Remote backup created.", affected_paths=[backup_path])
            except Exception as exc:
                return result_from_exception("Could not create remote backup.", exc)
        except Exception as exc:
            return result_from_exception("Could not create remote backup.", exc)

    async def calculate_checksum(self, remote_path: str, algorithm: str = "sha256") -> OperationResult:
        try:
            digest = hashlib.new(algorithm)
            async with self._sftp.open(remote_path, "rb") as handle:
                while True:
                    chunk = await handle.read(256 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            return OperationResult.success(
                f"Remote {algorithm} checksum calculated.",
                data=digest.hexdigest(),
                affected_paths=[remote_path],
            )
        except Exception as exc:
            return result_from_exception("Could not calculate remote checksum.", exc, retryable=True)

    async def _download_tree(self, remote_path: str, local_root: Path) -> None:
        attrs = await self._sftp.stat(remote_path)
        if self._is_dir(attrs):
            local_root.mkdir(parents=True, exist_ok=True)
            for name in await self._sftp.listdir(remote_path):
                await self._download_tree(posixpath.join(remote_path, name), local_root / name)
        else:
            local_root.parent.mkdir(parents=True, exist_ok=True)
            await self._sftp.get(remote_path, str(local_root))

    async def _delete_tree(self, remote_path: str) -> None:
        for name in await self._sftp.listdir(remote_path):
            child = posixpath.join(remote_path, name)
            attrs = await self._sftp.stat(child)
            if self._is_dir(attrs):
                await self._delete_tree(child)
            else:
                await self._sftp.remove(child)
        await self._sftp.rmdir(remote_path)

    def _item_from_attrs(self, name: str, path: str, attrs: Any) -> FileItem:
        mode = getattr(attrs, "permissions", None) or getattr(attrs, "mode", 0) or 0
        if stat.S_ISDIR(mode):
            kind = FileKind.DIRECTORY
        elif stat.S_ISLNK(mode):
            kind = FileKind.SYMLINK
        elif stat.S_ISREG(mode):
            kind = FileKind.FILE
        else:
            kind = FileKind.OTHER
        mtime = getattr(attrs, "mtime", None)
        return FileItem(
            name=name,
            path=path,
            kind=kind,
            size=getattr(attrs, "size", None) if kind == FileKind.FILE else None,
            modified_at=datetime.fromtimestamp(mtime).astimezone() if mtime else None,
            permissions=stat.filemode(mode) if mode else None,
            owner=str(getattr(attrs, "uid", "")) or None,
            group=str(getattr(attrs, "gid", "")) or None,
        )

    def _is_dir(self, attrs: Any) -> bool:
        mode = getattr(attrs, "permissions", None) or getattr(attrs, "mode", 0) or 0
        return stat.S_ISDIR(mode)

    def _wrap_progress(self, progress_callback: Callable[[str, str, int, int], None] | None):
        if progress_callback is None:
            return None

        def handler(source_path: bytes, destination_path: bytes, bytes_done: int, bytes_total: int) -> None:
            progress_callback(
                self._decode_path(source_path),
                self._decode_path(destination_path),
                bytes_done,
                bytes_total,
            )

        return handler

    def _decode_path(self, value: bytes | str) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value
