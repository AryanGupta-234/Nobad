from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.exceptions import RemoteEditConflictError
from core.result import OperationResult, result_from_exception
from editor.backup import backup_path_for
from editor.editor_session import EditorSession
from editor.encoding import detect_encoding, is_probably_binary
from file_ops.base import FileItem
from file_ops.temp_workspace import SecureTempWorkspace
from security.secret_scanner import is_sensitive_path


MAX_INLINE_EDIT_BYTES = 5 * 1024 * 1024


@dataclass
class RemoteEditManager:
    remote_ops: object
    workspace: SecureTempWorkspace
    backup_before_save: bool = True

    async def open_remote_file(self, remote_path: str) -> OperationResult:
        stat_result = await self.remote_ops.stat(remote_path)
        if not stat_result.ok:
            return stat_result
        item: FileItem = stat_result.data
        warnings: list[str] = []
        if item.size and item.size > MAX_INLINE_EDIT_BYTES:
            warnings.append("Large-file warning: this file is over 5 MB.")
        if is_sensitive_path(remote_path):
            warnings.append("Sensitive file warning: contents will not be written to logs.")

        local_path = self.workspace.path_for_remote(remote_path)
        download_result = await self.remote_ops.download_file(remote_path, local_path)
        if not download_result.ok:
            return download_result

        if is_probably_binary(local_path):
            return OperationResult.failure("This file appears to be binary and cannot be edited safely.")

        encoding = detect_encoding(local_path)
        session = EditorSession(
            local_path=Path(local_path),
            remote_path=remote_path,
            remote_modified_at=item.modified_at,
            encoding=encoding,
            backup_enabled=self.backup_before_save,
        )
        return OperationResult.success("Remote file opened for editing.", data=session, warnings=warnings)

    async def read_remote_text(self, session: EditorSession) -> OperationResult:
        if session.remote_path is None:
            return OperationResult.failure("This editor session is not attached to a remote file.")
        latest_path = self.workspace.path_for_remote(f"{session.remote_path}.remote-latest-{session.id}")
        stat_result = await self.remote_ops.stat(session.remote_path)
        if not stat_result.ok:
            return stat_result
        download = await self.remote_ops.download_file(session.remote_path, latest_path)
        if not download.ok:
            return download
        if is_probably_binary(latest_path):
            return OperationResult.failure("The latest remote file appears to be binary.")
        encoding = detect_encoding(latest_path)
        try:
            return OperationResult.success(
                "Latest remote file loaded.",
                data={
                    "text": latest_path.read_text(encoding=encoding),
                    "modified_at": stat_result.data.modified_at,
                    "encoding": encoding,
                },
            )
        except Exception as exc:
            return result_from_exception("Could not decode the latest remote file.", exc)

    async def save_remote_file(
        self,
        session: EditorSession,
        text: str,
        *,
        force: bool = False,
        remote_path: str | None = None,
    ) -> OperationResult:
        target_path = remote_path or session.remote_path
        if target_path is None:
            return OperationResult.failure("This editor session is not attached to a remote file.")
        try:
            if not force and remote_path is None:
                latest_result = await self.remote_ops.stat(target_path)
                if not latest_result.ok:
                    return latest_result
                latest: FileItem = latest_result.data
                if (
                    latest.modified_at
                    and session.remote_modified_at
                    and latest.modified_at.replace(microsecond=0) > session.remote_modified_at.replace(microsecond=0)
                ):
                    raise RemoteEditConflictError("Remote file changed after it was opened.")

            session.local_path.write_text(text, encoding=session.encoding)
            if self.backup_before_save and session.backup_enabled:
                existing = await self.remote_ops.stat(target_path)
                if existing.ok:
                    backup_result = await self.remote_ops.backup_file(target_path, backup_path_for(target_path))
                    if not backup_result.ok:
                        return backup_result

            upload_result = await self.remote_ops.upload_file(session.local_path, target_path)
            if not upload_result.ok:
                return upload_result
            refreshed = await self.remote_ops.stat(target_path)
            if refreshed.ok:
                session.remote_modified_at = refreshed.data.modified_at
            session.remote_path = target_path
            session.dirty = False
            return OperationResult.success("Remote file saved.", affected_paths=[target_path])
        except RemoteEditConflictError as exc:
            return OperationResult.failure(
                "Remote file changed after opening.",
                technical_details=str(exc),
                suggested_fix="Reload remote, save as a new file, compare changes, or overwrite intentionally.",
            )
        except Exception as exc:
            return result_from_exception("Could not save remote file.", exc, retryable=True)
