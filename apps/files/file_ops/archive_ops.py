from __future__ import annotations

import stat
import tarfile
import zipfile
from pathlib import Path

from core.result import OperationResult
from file_ops.archive_models import (
    ArchiveFormat,
    ArchiveMember,
    ArchiveOperationRequest,
    ArchivePreview,
    FolderSizeResult,
)
from file_ops.safety import UnsafePathError, safe_destination


class LocalArchiveOperations:
    async def preview(self, archive_path: str | Path, *, destination: str | Path = ".") -> OperationResult:
        return preview_archive(archive_path, destination)

    async def create(self, request: ArchiveOperationRequest) -> OperationResult:
        return create_archive(request)

    async def extract(self, archive_path: str | Path, destination: str | Path) -> OperationResult:
        return extract_archive_safely(archive_path, destination)

    async def calculate_folder_size(self, path: str | Path) -> OperationResult:
        return calculate_folder_size(path)


def preview_archive(archive_path: str | Path, destination: str | Path = ".") -> OperationResult:
    archive = Path(archive_path)
    destination_root = Path(destination)
    try:
        archive_format = archive_format_for_path(archive)
        members = archive_members(archive)
        warnings = archive_safety_warnings(members, destination_root)
        preview = ArchivePreview(
            archive_path=str(archive),
            format=archive_format,
            members=members,
            safe=not warnings,
            warnings=warnings,
        )
        if warnings:
            message = "Archive contains unsafe links." if any("link" in warning.lower() for warning in warnings) else "Archive contains unsafe paths."
            result = OperationResult.failure(
                message,
                technical_details="\n".join(warnings),
            )
            result.data = preview
            return result
        return OperationResult.success("Archive preview completed.", data=preview)
    except Exception as exc:
        return OperationResult.failure("Could not inspect archive.", technical_details=f"{type(exc).__name__}: {exc}")


def validate_archive_members(archive_path: str | Path, destination: str | Path) -> OperationResult:
    result = preview_archive(archive_path, destination)
    if not result.ok:
        return result
    preview: ArchivePreview = result.data
    return OperationResult.success("Archive members are safe to extract.", data=preview.member_names)


def archive_member_names(archive_path: str | Path) -> list[str]:
    return [member.name for member in archive_members(Path(archive_path))]


def archive_members(archive_path: Path) -> list[ArchiveMember]:
    archive_format = archive_format_for_path(archive_path)
    if archive_format == ArchiveFormat.ZIP:
        with zipfile.ZipFile(archive_path) as handle:
            members: list[ArchiveMember] = []
            for info in handle.infolist():
                mode = info.external_attr >> 16
                members.append(
                    ArchiveMember(
                        name=info.filename,
                        size=info.file_size,
                        is_link=stat.S_ISLNK(mode),
                    )
                )
            return members
    tar_mode = "r:gz" if archive_format == ArchiveFormat.TAR_GZ else "r:"
    with tarfile.open(archive_path, tar_mode) as handle:
        return [
            ArchiveMember(name=member.name, size=member.size, is_link=member.issym() or member.islnk())
            for member in handle.getmembers()
        ]


def detect_link_members(archive_path: str | Path) -> str | None:
    for member in archive_members(Path(archive_path)):
        if member.is_link:
            return f"Archive member is a link: {member.name}"
    return None


def archive_safety_warnings(members: list[ArchiveMember], destination_root: Path) -> list[str]:
    warnings: list[str] = []
    for member in members:
        if member.is_link:
            warnings.append(f"Archive member is a link: {member.name}")
            continue
        try:
            safe_destination(destination_root, member.name)
        except UnsafePathError as exc:
            warnings.append(str(exc))
    return warnings


def extract_archive_safely(archive_path: str | Path, destination: str | Path) -> OperationResult:
    validation = preview_archive(archive_path, destination)
    if not validation.ok:
        return validation
    archive = Path(archive_path)
    destination_root = Path(destination)
    try:
        archive_format = archive_format_for_path(archive)
        destination_root.mkdir(parents=True, exist_ok=True)
        if archive_format == ArchiveFormat.ZIP:
            with zipfile.ZipFile(archive) as handle:
                handle.extractall(destination_root)
        elif archive_format == ArchiveFormat.TAR_GZ:
            with tarfile.open(archive, "r:gz") as handle:
                handle.extractall(destination_root, filter="data")
        else:
            with tarfile.open(archive, "r:") as handle:
                handle.extractall(destination_root, filter="data")
        return OperationResult.success("Archive extracted.", affected_paths=[str(archive), str(destination_root)])
    except Exception as exc:
        return OperationResult.failure("Archive extraction failed.", technical_details=f"{type(exc).__name__}: {exc}")


def create_archive(request: ArchiveOperationRequest) -> OperationResult:
    destination = Path(request.destination)
    sources = [Path(source).expanduser() for source in request.sources]
    try:
        if not sources:
            return OperationResult.failure("No archive sources selected.")
        for source in sources:
            if not source.exists():
                return OperationResult.failure(f"Archive source does not exist: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if request.archive_format == ArchiveFormat.ZIP:
            _create_zip(destination, sources)
        elif request.archive_format == ArchiveFormat.TAR_GZ:
            _create_tar_gz(destination, sources)
        else:
            return OperationResult.failure(f"Unsupported archive format: {request.archive_format}")
        return OperationResult.success("Archive created.", affected_paths=[str(destination)], data=str(destination))
    except Exception as exc:
        return OperationResult.failure("Archive creation failed.", technical_details=f"{type(exc).__name__}: {exc}")


def calculate_folder_size(path: str | Path) -> OperationResult:
    target = Path(path).expanduser()
    try:
        if target.is_file():
            size = target.stat().st_size
        else:
            size = sum(file.stat().st_size for file in target.rglob("*") if file.is_file())
        return OperationResult.success(
            "Folder size calculated.",
            data=FolderSizeResult(path=str(target), size_bytes=size, source="local"),
        )
    except Exception as exc:
        return OperationResult.failure("Could not calculate folder size.", technical_details=f"{type(exc).__name__}: {exc}")


def archive_format_for_path(path: str | Path) -> ArchiveFormat:
    name = str(path).lower()
    if name.endswith(".zip"):
        return ArchiveFormat.ZIP
    if name.endswith(".tar"):
        return ArchiveFormat.TAR
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return ArchiveFormat.TAR_GZ
    raise ValueError(f"Unsupported archive format: {path}")


def _create_zip(destination: Path, sources: list[Path]) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for source in sources:
            _write_zip_source(handle, source)


def _write_zip_source(handle: zipfile.ZipFile, source: Path) -> None:
    if source.is_file():
        handle.write(source, source.name)
        return
    added_any = False
    for child in source.rglob("*"):
        archive_name = str(Path(source.name) / child.relative_to(source))
        if child.is_dir():
            added_any = True
            handle.writestr(archive_name.rstrip("/") + "/", "")
        elif child.is_file():
            added_any = True
            handle.write(child, archive_name)
    if not added_any:
        handle.writestr(source.name.rstrip("/") + "/", "")


def _create_tar_gz(destination: Path, sources: list[Path]) -> None:
    with tarfile.open(destination, "w:gz") as handle:
        for source in sources:
            handle.add(source, arcname=source.name, recursive=True)
