from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from core.result import OperationResult, result_from_exception
from file_ops.metadata import local_file_item


class LocalFileOperations:
    async def list_dir(self, path: str | Path, *, show_hidden: bool = False) -> OperationResult:
        def _list() -> list:
            root = Path(path).expanduser()
            items = []
            for child in sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                if not show_hidden and child.name.startswith("."):
                    continue
                items.append(local_file_item(child))
            return items

        try:
            return OperationResult.success("Local directory listed.", data=await asyncio.to_thread(_list))
        except Exception as exc:
            return result_from_exception("Could not list local directory.", exc)

    async def create_file(self, path: str | Path) -> OperationResult:
        try:
            target = Path(path)
            await asyncio.to_thread(target.touch, exist_ok=False)
            return OperationResult.success("Local file created.", affected_paths=[str(target)])
        except Exception as exc:
            return result_from_exception("Could not create local file.", exc)

    async def create_folder(self, path: str | Path) -> OperationResult:
        try:
            target = Path(path)
            await asyncio.to_thread(target.mkdir, parents=True, exist_ok=False)
            return OperationResult.success("Local folder created.", affected_paths=[str(target)])
        except Exception as exc:
            return result_from_exception("Could not create local folder.", exc)

    async def rename(self, source: str | Path, destination: str | Path) -> OperationResult:
        try:
            src = Path(source)
            dst = Path(destination)
            await asyncio.to_thread(src.rename, dst)
            return OperationResult.success("Local item renamed.", affected_paths=[str(src), str(dst)])
        except Exception as exc:
            return result_from_exception("Could not rename local item.", exc)

    async def delete(self, path: str | Path, *, recursive: bool = False) -> OperationResult:
        try:
            target = Path(path)
            if target.is_dir():
                if recursive:
                    await asyncio.to_thread(shutil.rmtree, target)
                else:
                    await asyncio.to_thread(target.rmdir)
            else:
                await asyncio.to_thread(target.unlink)
            return OperationResult.success("Local item deleted.", affected_paths=[str(target)])
        except Exception as exc:
            return result_from_exception("Could not delete local item.", exc)

    async def copy(self, source: str | Path, destination: str | Path) -> OperationResult:
        try:
            src = Path(source)
            dst = Path(destination)
            if src.is_dir():
                await asyncio.to_thread(shutil.copytree, src, dst)
            else:
                await asyncio.to_thread(shutil.copy2, src, dst)
            return OperationResult.success("Local item copied.", affected_paths=[str(src), str(dst)])
        except Exception as exc:
            return result_from_exception("Could not copy local item.", exc)

