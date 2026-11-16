from __future__ import annotations

import posixpath
import re
from pathlib import Path

from core.result import OperationResult
from file_ops.archive_models import (
    ArchiveFormat,
    ArchiveMember,
    ArchiveOperationRequest,
    ArchivePreview,
    FolderSizeResult,
)
from file_ops.archive_ops import archive_format_for_path, archive_safety_warnings


class RemoteArchiveOperations:
    def __init__(self, connection) -> None:  # type: ignore[no-untyped-def]
        self.connection = connection

    async def preview(self, archive_path: str, *, destination: str = ".") -> OperationResult:
        try:
            archive_format = archive_format_for_path(archive_path)
        except ValueError as exc:
            return OperationResult.failure(str(exc))
        if archive_format == ArchiveFormat.ZIP:
            command_result = await self._require_command("unzip")
            if not command_result.ok:
                return command_result
            list_result = await self._run_checked(f"unzip -l {sh_quote(archive_path)}")
            if not list_result.ok:
                return list_result
            metadata_result = await self._run_checked(f"unzip -Z -l {sh_quote(archive_path)}")
            members = parse_unzip_listing(list_result.data["stdout"])
            link_warnings: list[str] = []
            if metadata_result.ok:
                link_warnings = parse_zipinfo_link_warnings(metadata_result.data["stdout"])
            else:
                link_warnings.append("Could not inspect zip link metadata with unzip -Z.")
        else:
            command_result = await self._require_command("tar")
            if not command_result.ok:
                return command_result
            tar_flag = "-tvzf" if archive_format == ArchiveFormat.TAR_GZ else "-tvf"
            list_result = await self._run_checked(f"tar {tar_flag} {sh_quote(archive_path)}")
            if not list_result.ok:
                return list_result
            members, link_warnings = parse_tar_verbose_listing(list_result.data["stdout"])

        warnings = archive_safety_warnings(members, Path(destination or ".")) + link_warnings
        preview = ArchivePreview(
            archive_path=archive_path,
            format=archive_format,
            members=members,
            safe=not warnings,
            warnings=warnings,
        )
        if warnings:
            result = OperationResult.failure("Archive preview found unsafe members.", technical_details="\n".join(warnings))
            result.data = preview
            return result
        return OperationResult.success("Remote archive preview completed.", data=preview)

    async def create(self, request: ArchiveOperationRequest) -> OperationResult:
        sources = [str(source) for source in request.sources]
        if not sources:
            return OperationResult.failure("No remote archive sources selected.")
        destination = str(request.destination)
        if request.archive_format == ArchiveFormat.ZIP:
            required = await self._require_command("zip")
            if not required.ok:
                return required
            command = build_remote_zip_create_command(sources, destination)
        elif request.archive_format == ArchiveFormat.TAR_GZ:
            required = await self._require_command("tar")
            if not required.ok:
                return required
            command = build_remote_tar_create_command(sources, destination)
        else:
            return OperationResult.failure(f"Unsupported archive format: {request.archive_format}")
        result = await self._run_checked(command)
        if not result.ok:
            return result
        return OperationResult.success("Remote archive created.", affected_paths=[destination], data=destination)

    async def extract(self, archive_path: str, destination: str) -> OperationResult:
        preview = await self.preview(archive_path, destination=destination)
        if not preview.ok:
            return preview
        archive_format = archive_format_for_path(archive_path)
        if archive_format == ArchiveFormat.ZIP:
            required = await self._require_command("unzip")
            if not required.ok:
                return required
            command = f"mkdir -p {sh_quote(destination)} && unzip -q {sh_quote(archive_path)} -d {sh_quote(destination)}"
        elif archive_format == ArchiveFormat.TAR_GZ:
            required = await self._require_command("tar")
            if not required.ok:
                return required
            command = f"mkdir -p {sh_quote(destination)} && tar -xzf {sh_quote(archive_path)} -C {sh_quote(destination)}"
        else:
            required = await self._require_command("tar")
            if not required.ok:
                return required
            command = f"mkdir -p {sh_quote(destination)} && tar -xf {sh_quote(archive_path)} -C {sh_quote(destination)}"
        result = await self._run_checked(command)
        if not result.ok:
            return result
        return OperationResult.success("Remote archive extracted.", affected_paths=[archive_path, destination])

    async def calculate_folder_size(self, remote_path: str) -> OperationResult:
        required = await self._require_command("du")
        if not required.ok:
            return required
        result = await self._run_checked(f"du -sb {sh_quote(remote_path)}")
        multiplier = 1
        if not result.ok:
            result = await self._run_checked(f"du -sk {sh_quote(remote_path)}")
            multiplier = 1024
        if not result.ok:
            return result
        try:
            size = int(result.data["stdout"].split()[0]) * multiplier
        except Exception as exc:
            return OperationResult.failure("Could not parse remote folder size.", technical_details=f"{type(exc).__name__}: {exc}")
        return OperationResult.success(
            "Remote folder size calculated.",
            data=FolderSizeResult(path=remote_path, size_bytes=size, source="remote"),
        )

    async def _require_command(self, command: str) -> OperationResult:
        result = await self.connection.run_command(f"command -v {sh_quote(command)}")
        if not result.ok:
            return result
        if result.data.get("exit_status") != 0:
            return OperationResult.failure(
                f"Remote command unavailable: {command}.",
                technical_details=result.data.get("stderr") or result.data.get("stdout"),
                suggested_fix="Install the command on the server or use local relay mode.",
            )
        return OperationResult.success(f"Remote command available: {command}.")

    async def _run_checked(self, command: str) -> OperationResult:
        result = await self.connection.run_command(command)
        if not result.ok:
            return result
        if result.data.get("exit_status") != 0:
            return OperationResult.failure(
                "Remote archive command failed.",
                technical_details=(result.data.get("stderr") or result.data.get("stdout") or "").strip(),
            )
        return result


def build_remote_zip_create_command(sources: list[str], destination: str) -> str:
    parent, names = common_parent_and_names(sources)
    return f"cd {sh_quote(parent)} && zip -r {sh_quote(destination)} {' '.join(sh_quote(name) for name in names)}"


def build_remote_tar_create_command(sources: list[str], destination: str) -> str:
    parent, names = common_parent_and_names(sources)
    return f"cd {sh_quote(parent)} && tar -czf {sh_quote(destination)} {' '.join(sh_quote(name) for name in names)}"


def common_parent_and_names(sources: list[str]) -> tuple[str, list[str]]:
    parents = {posixpath.dirname(source.rstrip("/")) or "." for source in sources}
    if len(parents) == 1:
        parent = next(iter(parents))
        return parent, [posixpath.basename(source.rstrip("/")) for source in sources]
    return ".", sources


def parse_unzip_listing(output: str) -> list[ArchiveMember]:
    members: list[ArchiveMember] = []
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+(.+)$", line)
        if match:
            members.append(ArchiveMember(name=match.group(2), size=int(match.group(1))))
    return members


def parse_zipinfo_link_warnings(output: str) -> list[str]:
    warnings: list[str] = []
    for line in output.splitlines():
        if line.startswith("l"):
            name = line.rsplit(maxsplit=1)[-1]
            warnings.append(f"Archive member is a link: {name}")
    return warnings


def parse_tar_verbose_listing(output: str) -> tuple[list[ArchiveMember], list[str]]:
    members: list[ArchiveMember] = []
    warnings: list[str] = []
    for line in output.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 6:
            continue
        mode, _owner_group, size, _date, _time, name = parts
        clean_name = name.split(" -> ", 1)[0]
        is_link = mode.startswith("l") or mode.startswith("h")
        members.append(ArchiveMember(name=clean_name, size=int(size) if size.isdigit() else None, is_link=is_link))
        if is_link:
            warnings.append(f"Archive member is a link: {clean_name}")
    return members, warnings


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
