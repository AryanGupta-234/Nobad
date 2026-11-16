from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

from core.connections.ftp_client import FTPConnection
from core.connections.profile import AuthType, ConnectionProfile, ProfileType, ProtocolType
from editor.diff_engine import TextDiffEngine
from file_ops.base import FileItem, FileKind
from file_ops.ftp_ops import FTPFileOperations
from storage.database import init_database
from storage.repositories import SyncBaselineRepository
from sync.baseline import SyncBaseline, SyncBaselineEntry, SyncFileState
from sync.conflicts import SyncConflictChoice, SyncConflictDecision, SyncConflictResolver
from sync.diff_engine import SyncAction, SyncManifestEntry
from sync.sync_job import SyncJob, SyncMode
from sync.sync_planner import SyncPlanner
from transfers.remote_transfer import RemoteEndpoint, RemoteTransferMode, RemoteTransferService
from transfers.transfer_manager import TransferManager
from transfers.transfer_job import TransferStatus


def test_migration_adds_connection_options_to_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE connection_profiles ("
        "id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, profile_type VARCHAR NOT NULL, "
        "protocol VARCHAR NOT NULL, host VARCHAR NOT NULL, port INTEGER NOT NULL, "
        "username VARCHAR NOT NULL, auth_type VARCHAR NOT NULL)"
    )
    connection.commit()
    connection.close()

    session_factory = init_database(database)
    columns = {column["name"] for column in inspect(session_factory.kw["bind"]).get_columns("connection_profiles")}
    tables = set(inspect(session_factory.kw["bind"]).get_table_names())

    assert "options" in columns
    assert {"schema_migrations", "sync_baselines", "sync_baseline_entries"} <= tables


def test_text_diff_engine_reports_changed_hunks() -> None:
    hunks = TextDiffEngine().compare("one\ntwo\n", "one\nthree\n")

    assert [hunk.tag for hunk in hunks] == ["equal", "replace"]
    assert hunks[1].left_start == 1
    assert hunks[1].right_start == 1


def test_two_way_baseline_propagates_one_sided_change() -> None:
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new = datetime(2026, 1, 2, tzinfo=timezone.utc)
    job = SyncJob("Two way", SyncMode.TWO_WAY, "/local", "/remote")
    baseline = SyncBaseline(
        job_id=job.id,
        local_root="/local",
        remote_root="/remote",
        entries={
            "app.py": SyncBaselineEntry(
                "app.py",
                SyncFileState(True, 10, old, "old"),
                SyncFileState(True, 10, old, "old"),
            )
        },
    )

    preview = SyncPlanner().preview_from_manifests(
        job,
        [SyncManifestEntry("app.py", 12, new, checksum="new")],
        [SyncManifestEntry("app.py", 10, old, checksum="old")],
        baseline,
    )

    assert preview.overwrites == ["app.py"]
    assert preview.entries[0].source_side.value == "local"


def test_two_way_baseline_detects_delete_vs_modify_conflict() -> None:
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new = datetime(2026, 1, 2, tzinfo=timezone.utc)
    job = SyncJob("Two way", SyncMode.TWO_WAY, "/local", "/remote")
    baseline = SyncBaseline(
        job_id=job.id,
        local_root="/local",
        remote_root="/remote",
        entries={
            "app.py": SyncBaselineEntry(
                "app.py",
                SyncFileState(True, 10, old, "old"),
                SyncFileState(True, 10, old, "old"),
            )
        },
    )

    preview = SyncPlanner().preview_from_manifests(
        job,
        [],
        [SyncManifestEntry("app.py", 12, new, checksum="new")],
        baseline,
    )

    assert preview.conflicts == ["app.py"]


def test_conflict_keep_both_generates_safe_alternate_name() -> None:
    preview = SyncPlanner().preview_from_manifests(
        SyncJob("Two way", SyncMode.TWO_WAY, "/local", "/remote"),
        [SyncManifestEntry("config/app.json", 10)],
        [SyncManifestEntry("config/app.json", 20)],
    )

    resolved = SyncConflictResolver().resolve(
        preview,
        [SyncConflictDecision("config/app.json", SyncConflictChoice.KEEP_BOTH)],
        timestamp=datetime(2026, 6, 15, 12, 30),
    ).preview

    entry = resolved.entries[0]
    assert entry.action == SyncAction.KEEP_BOTH
    assert entry.alternate_path == "config/app.remote-conflict-20260615-123000.json"
    assert resolved.conflicts == []


def test_sync_baseline_repository_replaces_atomically(tmp_path: Path) -> None:
    session_factory = init_database(tmp_path / "app.sqlite3")
    job = SyncJob("Two way", SyncMode.TWO_WAY, "/local", "/remote")
    with session_factory() as session:
        from storage.repositories import SyncJobRepository

        SyncJobRepository(session).add(job)
        SyncBaselineRepository(session).replace(
            SyncBaseline(
                job_id=job.id,
                local_root="/local",
                remote_root="/remote",
                entries={"a.txt": SyncBaselineEntry("a.txt", SyncFileState(True, 1), SyncFileState(True, 1))},
            )
        )
        session.commit()
    with session_factory() as session:
        loaded = SyncBaselineRepository(session).get_for_job(job.id)

    assert loaded is not None
    assert loaded.entries["a.txt"].local.size == 1


class _MemoryStream:
    def __init__(self, initial: bytes = b"") -> None:
        self.data = bytearray(initial)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def write(self, block: bytes) -> None:
        self.data.extend(block)

    async def iter_by_block(self, count: int):
        for offset in range(0, len(self.data), count):
            yield bytes(self.data[offset : offset + count])


class _MemoryFTPClient:
    def __init__(self) -> None:
        self.files = {"/remote.txt": b"remote-data"}
        self.uploads: dict[str, _MemoryStream] = {}

    def upload_stream(self, destination: str):
        stream = _MemoryStream()
        self.uploads[destination] = stream
        return stream

    def download_stream(self, source: str):
        return _MemoryStream(self.files[source])

    async def stat(self, path: str):
        return {"type": "file", "size": str(len(self.files[path])), "modify": "20260615120000"}


@pytest.mark.asyncio
async def test_ftp_file_operations_stream_progress(tmp_path: Path) -> None:
    client = _MemoryFTPClient()
    operations = FTPFileOperations(client, block_size=4)
    progress: list[tuple[int, int]] = []
    local = tmp_path / "download.txt"

    downloaded = await operations.download_file(
        "/remote.txt",
        local,
        progress_callback=lambda _source, _destination, done, total: progress.append((done, total)),
    )
    source = tmp_path / "upload.txt"
    source.write_bytes(b"upload-data")
    uploaded = await operations.upload_file(source, "/uploaded.txt")

    assert downloaded.ok and uploaded.ok
    assert local.read_bytes() == b"remote-data"
    assert bytes(client.uploads["/uploaded.txt"].data) == b"upload-data"
    assert progress[-1] == (11, 11)


@pytest.mark.asyncio
async def test_ftps_connection_applies_tls_options(monkeypatch) -> None:
    events: list[str] = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            events.append(f"init:{bool(kwargs.get('ssl'))}")

        async def connect(self, host: str, port: int) -> None:
            events.append(f"connect:{host}:{port}")

        async def upgrade_to_tls(self, _context) -> None:
            events.append("tls")

        async def login(self, username: str, password: str) -> None:
            events.append(f"login:{username}:{password}")

    monkeypatch.setattr("core.connections.ftp_client.aioftp", SimpleNamespace(Client=FakeClient))
    profile = ConnectionProfile(
        name="Secure FTP",
        profile_type=ProfileType.FTPS,
        protocol=ProtocolType.FTPS,
        host="ftp.example.com",
        port=21,
        username="user",
        auth_type=AuthType.PASSWORD,
        options={"tls_mode": "explicit", "verify_tls": True},
    )

    result = await FTPConnection(profile, secure=True).connect(password="secret")

    assert result.ok
    assert events == ["init:False", "connect:ftp.example.com:21", "tls", "login:user:secret"]


class _RelayOps:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})

    async def list_dir(self, path: str, *, show_hidden: bool = False):
        del show_hidden
        from core.result import OperationResult

        prefix = path.rstrip("/") + "/"
        return OperationResult.success(
            "listed",
            data=[
                FileItem(Path(name).name, name, FileKind.FILE, len(data))
                for name, data in self.files.items()
                if name.startswith(prefix) and "/" not in name[len(prefix) :]
            ],
        )

    async def stat(self, path: str):
        from core.result import OperationResult

        if path not in self.files:
            return OperationResult.failure("missing")
        return OperationResult.success("stat", data=FileItem(Path(path).name, path, FileKind.FILE, len(self.files[path])))

    async def download_file(self, remote_path: str, local_path: Path, *, progress_callback=None):
        from core.result import OperationResult

        data = self.files[remote_path]
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        if progress_callback:
            progress_callback(remote_path, str(local_path), len(data), len(data))
        return OperationResult.success("downloaded")

    async def upload_file(self, local_path: Path, remote_path: str, *, progress_callback=None):
        from core.result import OperationResult

        data = Path(local_path).read_bytes()
        self.files[remote_path] = data
        if progress_callback:
            progress_callback(str(local_path), remote_path, len(data), len(data))
        return OperationResult.success("uploaded")

    async def ensure_folder(self, path: str):
        from core.result import OperationResult

        return OperationResult.success(path)

    async def rename(self, source: str, destination: str):
        from core.result import OperationResult

        self.files[destination] = self.files.pop(source)
        return OperationResult.success("renamed")

    async def delete(self, path: str, *, recursive: bool = False):
        from core.result import OperationResult

        del recursive
        self.files.pop(path, None)
        return OperationResult.success("deleted")


@pytest.mark.asyncio
async def test_remote_transfer_local_relay_completes_and_cleans_part() -> None:
    source_ops = _RelayOps({"/source/a.txt": b"hello"})
    destination_ops = _RelayOps()
    source_connection = SimpleNamespace(profile=SimpleNamespace(id="source"), capabilities=SimpleNamespace(can_exec_command=False))
    destination_connection = SimpleNamespace(
        profile=SimpleNamespace(id="destination"),
        capabilities=SimpleNamespace(can_exec_command=False),
    )
    manager = TransferManager(max_concurrent=2)
    service = RemoteTransferService(manager)
    preview = await service.preview(
        RemoteEndpoint("source", "Source", source_connection, source_ops),
        RemoteEndpoint("destination", "Destination", destination_connection, destination_ops),
        FileItem("a.txt", "/source/a.txt", FileKind.FILE, 5),
        "/target",
        mode=RemoteTransferMode.AUTO,
    )

    result = await service.execute(preview.data)

    assert result.ok
    assert destination_ops.files["/target/a.txt"] == b"hello"
    assert not any(".part-" in path for path in destination_ops.files)
    assert result.data[0].status == TransferStatus.COMPLETED


@pytest.mark.asyncio
async def test_remote_transfer_preview_rejects_protected_destination() -> None:
    source_ops = _RelayOps({"/source/a.txt": b"hello"})
    destination_ops = _RelayOps()
    source_connection = SimpleNamespace(profile=SimpleNamespace(id="source"), capabilities=SimpleNamespace(can_exec_command=False))
    destination_connection = SimpleNamespace(
        profile=SimpleNamespace(id="destination"),
        capabilities=SimpleNamespace(can_exec_command=False),
    )

    result = await RemoteTransferService(TransferManager()).preview(
        RemoteEndpoint("source", "Source", source_connection, source_ops),
        RemoteEndpoint("destination", "Destination", destination_connection, destination_ops),
        FileItem("a.txt", "/source/a.txt", FileKind.FILE, 5),
        "/",
    )

    assert not result.ok
    assert "protected path" in result.technical_details
