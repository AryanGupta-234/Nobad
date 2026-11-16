from __future__ import annotations

import posixpath
from dataclasses import dataclass

from core.connections.ssh_async import sh_quote
from core.result import OperationResult
from file_ops.safety import normalize_remote_path

from deployment.deployment_job import DeploymentJob, DeploymentPreview


@dataclass(frozen=True, slots=True)
class DeploymentBackup:
    target_existed: bool
    archive_path: str | None = None
    archive_format: str | None = None


class BackupManager:
    async def create_backup(
        self,
        connection,
        job: DeploymentJob,
        preview: DeploymentPreview,
    ) -> OperationResult:
        if not preview.target_exists:
            return OperationResult.success(
                "Remote target does not exist; rollback will remove the newly created target.",
                data=DeploymentBackup(target_existed=False),
            )

        tool = await self._archive_tool(connection)
        if not tool.ok:
            return tool
        archive_format = str(tool.data)
        archive_path = preview.backup_archive_path
        if archive_format == "zip":
            archive_path = archive_path.removesuffix(".tar.gz") + ".zip"

        target = normalize_remote_path(job.remote_target_folder)
        parent = posixpath.dirname(target.rstrip("/")) or "/"
        target_name = posixpath.basename(target.rstrip("/"))
        archive_member = f"./{target_name}"
        backup_dir = posixpath.dirname(archive_path)
        if archive_format == "tar.gz":
            command = (
                f"mkdir -p {sh_quote(backup_dir)} && "
                f"tar -czf {sh_quote(archive_path)} -C {sh_quote(parent)} {sh_quote(archive_member)}"
            )
        else:
            command = (
                f"mkdir -p {sh_quote(backup_dir)} && "
                f"cd {sh_quote(parent)} && zip -qr {sh_quote(archive_path)} {sh_quote(archive_member)}"
            )
        result = await self._run_checked(connection, command, "Could not create remote deployment backup.")
        if not result.ok:
            return result
        return OperationResult.success(
            "Remote deployment backup created.",
            data=DeploymentBackup(True, archive_path, archive_format),
            affected_paths=[archive_path],
        )

    async def restore_backup(
        self,
        connection,
        job: DeploymentJob,
        backup: DeploymentBackup,
        *,
        run_id: str,
    ) -> OperationResult:
        target = normalize_remote_path(job.remote_target_folder)
        parent = posixpath.dirname(target.rstrip("/")) or "/"
        target_name = posixpath.basename(target.rstrip("/"))
        if not backup.target_existed:
            command = f"rm -rf -- {sh_quote(target)}"
            return await self._run_checked(connection, command, "Could not remove the new deployment target.")
        if not backup.archive_path or not backup.archive_format:
            return OperationResult.failure("Rollback backup metadata is incomplete.")

        staging = posixpath.join(parent, f".rfm-restore-{run_id}")
        failed = posixpath.join(parent, f".rfm-failed-{run_id}")
        candidate = posixpath.join(staging, target_name)
        if backup.archive_format == "tar.gz":
            extract = f"tar -xzf {sh_quote(backup.archive_path)} -C {sh_quote(staging)}"
        else:
            extract = f"unzip -q {sh_quote(backup.archive_path)} -d {sh_quote(staging)}"
        command = (
            f"rm -rf -- {sh_quote(staging)} {sh_quote(failed)} && "
            f"mkdir -p {sh_quote(staging)} && {extract} && "
            f"test -e {sh_quote(candidate)} && "
            f"if test -e {sh_quote(target)}; then mv -- {sh_quote(target)} {sh_quote(failed)}; fi && "
            f"(mv -- {sh_quote(candidate)} {sh_quote(target)} || "
            f"(test -e {sh_quote(failed)} && mv -- {sh_quote(failed)} {sh_quote(target)} && exit 1)) && "
            f"rm -rf -- {sh_quote(staging)} {sh_quote(failed)}"
        )
        return await self._run_checked(connection, command, "Automatic rollback failed.")

    async def prune_backups(self, connection, backup_directory: str, retention: int = 5) -> OperationResult:  # type: ignore[no-untyped-def]
        keep = max(1, min(50, int(retention)))
        command = (
            f"if test -d {sh_quote(backup_directory)}; then "
            f"find {sh_quote(backup_directory)} -maxdepth 1 -type f "
            f"\\( -name '*.tar.gz' -o -name '*.zip' \\) -printf '%T@ %p\\n' "
            f"| sort -nr | tail -n +{keep + 1} | cut -d' ' -f2- | xargs -r rm --; fi"
        )
        return await self._run_checked(connection, command, "Could not prune old deployment backups.")

    async def list_backups(self, connection, backup_directory: str) -> OperationResult:  # type: ignore[no-untyped-def]
        command = (
            f"if test -d {sh_quote(backup_directory)}; then "
            f"find {sh_quote(backup_directory)} -maxdepth 1 -type f "
            f"\\( -name '*.tar.gz' -o -name '*.zip' \\) -printf '%T@|%s|%p\\n' | sort -nr; fi"
        )
        result = await connection.run_command(command)
        if not result.ok or self._exit_status(result) != 0:
            data = result.data if isinstance(result.data, dict) else {}
            return OperationResult.failure(
                "Could not list deployment backups.",
                technical_details=str(data.get("stderr") or result.technical_details or "") or None,
            )
        data = result.data if isinstance(result.data, dict) else {}
        backups = []
        for line in str(data.get("stdout") or "").splitlines():
            timestamp, separator, remainder = line.partition("|")
            size, separator_two, path = remainder.partition("|")
            if not separator or not separator_two or not path:
                continue
            backups.append(
                {
                    "path": path,
                    "format": "tar.gz" if path.endswith(".tar.gz") else "zip",
                    "timestamp": float(timestamp or 0),
                    "size": int(size or 0),
                }
            )
        return OperationResult.success("Deployment backups listed.", data=backups)

    async def _archive_tool(self, connection) -> OperationResult:  # type: ignore[no-untyped-def]
        result = await connection.run_command(
            "if command -v tar >/dev/null 2>&1; then printf tar; "
            "elif command -v zip >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1; then printf zip; "
            "else exit 127; fi"
        )
        if not result.ok or self._exit_status(result) != 0:
            return OperationResult.failure(
                "Deployment blocked because no reliable remote backup command is available.",
                suggested_fix="Install tar, or install both zip and unzip, on the target server.",
            )
        output = str((result.data or {}).get("stdout", "")).strip()
        if output not in {"tar", "zip"}:
            return OperationResult.failure("Remote backup command detection returned an unexpected result.")
        return OperationResult.success("Remote backup tool detected.", data="tar.gz" if output == "tar" else "zip")

    async def _run_checked(self, connection, command: str, message: str) -> OperationResult:  # type: ignore[no-untyped-def]
        result = await connection.run_command(command)
        if result.ok and self._exit_status(result) == 0:
            return result
        data = result.data or {}
        details = str(data.get("stderr") or result.technical_details or "").strip() or None
        return OperationResult.failure(message, technical_details=details)

    def _exit_status(self, result: OperationResult) -> int:
        data = result.data if isinstance(result.data, dict) else {}
        return int(data.get("exit_status", 1))
