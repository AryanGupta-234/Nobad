from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from sqlalchemy import inspect

from core.result import OperationResult
from deployment.deployment_executor import DeploymentExecutor
from deployment.deployment_history import DeploymentHistoryService, bounded_excerpt
from deployment.deployment_job import (
    DeploymentArtifact,
    DeploymentArtifactKind,
    DeploymentExecutionPolicy,
    DeploymentJob,
    DeploymentPreview,
    DeploymentRun,
    DeploymentRunStatus,
    DeploymentStage,
    DeploymentStageEvent,
    DeploymentStrategy,
    HealthCheckConfig,
    HealthCheckOrigin,
    HealthCheckResult,
)
from deployment.deployment_lock import DeploymentLock, DeploymentLockManager
from deployment.health_checks import HealthCheckService, REMOTE_STATUS_MARKER
from deployment.release_manager import AtomicReleaseContext, ReleaseManager
from storage.app_data import AppDataService
from storage.database import init_database
from sync.diff_engine import SyncPreview


class CommandConnection:
    def __init__(self, responder=None) -> None:  # type: ignore[no-untyped-def]
        self.responder = responder
        self.commands: list[tuple[str, str | None]] = []

    async def run_command(self, command: str, *, cwd: str | None = None) -> OperationResult:
        self.commands.append((command, cwd))
        if self.responder:
            return self.responder(command, cwd)
        return OperationResult.success(
            "Ran.",
            data={"stdout": "", "stderr": "", "exit_status": 0},
        )


def empty_preview(tmp_path: Path, *, digest: str = "") -> DeploymentPreview:
    return DeploymentPreview(
        sync_preview=SyncPreview(),
        target_exists=False,
        backup_directory="/srv/.rfm-backups/job",
        backup_archive_path="/srv/.rfm-backups/job/site.tar.gz",
        local_root=str(tmp_path),
        remote_root="/srv/site",
        digest=digest,
    )


def test_phase3g_database_tables_and_history_round_trip(tmp_path) -> None:
    database = tmp_path / "app.sqlite3"
    session_factory = init_database(database)
    tables = set(inspect(session_factory.kw["bind"]).get_table_names())
    assert {"deployment_runs", "deployment_run_stages", "deployment_artifacts"} <= tables

    app_data = AppDataService.create(database)
    history = DeploymentHistoryService(app_data)
    run = DeploymentRun(
        job_id="job-1",
        profile_id="profile-1",
        profile_name="Production",
        host="example.com",
        remote_target="/srv/site",
        strategy=DeploymentStrategy.ATOMIC_RELEASE,
    )
    history.start_run(run)
    history.begin_stage(
        DeploymentStageEvent(
            "job-1",
            DeploymentStage.HEALTH_CHECK,
            "Checking token=top-secret",
            run_id=run.id,
        )
    )
    history.append_stage_output(run.id, "password=hunter2")
    history.add_artifact(
        DeploymentArtifact(
            run_id=run.id,
            job_id="job-1",
            profile_id="profile-1",
            kind=DeploymentArtifactKind.RELEASE,
            path="/srv/.rfm-releases/job-1/release-1",
            active=True,
        )
    )
    history.finish_run(
        run.id,
        status=DeploymentRunStatus.SUCCESS,
        message="Completed.",
        health_ok=True,
    )

    loaded = history.list_runs("job-1")[0]
    stage = history.list_stages(run.id)[0]
    artifact = history.list_artifacts("job-1")[0]
    assert loaded.status == DeploymentRunStatus.SUCCESS
    assert loaded.health_ok is True
    assert "hunter2" not in stage.output_excerpt
    assert artifact.active


def test_bounded_history_excerpt_keeps_head_and_tail_and_redacts() -> None:
    excerpt = bounded_excerpt("", "password=secret\n" + ("x" * 9000) + "\ntail")
    assert len(excerpt.encode("utf-8")) <= 8192
    assert "secret" not in excerpt
    assert "tail" in excerpt
    assert "truncated" in excerpt


@pytest.mark.asyncio
async def test_health_check_command_failure_returns_structured_result() -> None:
    connection = CommandConnection(
        lambda _command, _cwd: OperationResult.success(
            "Ran.",
            data={"stdout": "", "stderr": "unhealthy", "exit_status": 1},
        )
    )
    result = await HealthCheckService().run(
        connection,
        HealthCheckConfig(command="check-health"),
        cwd="/srv/site",
    )

    assert not result.ok
    assert isinstance(result.data, HealthCheckResult)
    assert result.data.command_ok is False
    assert result.data.technical_details == "unhealthy"


@pytest.mark.asyncio
async def test_desktop_and_remote_http_health_checks() -> None:
    class StubDesktopHealthService(HealthCheckService):
        async def _desktop_http(self, config) -> OperationResult:  # type: ignore[no-untyped-def]
            return OperationResult.success(
                "Received.",
                data={"status_code": 204, "body": ""},
            )

    desktop = await StubDesktopHealthService().run(
            CommandConnection(),
            HealthCheckConfig(
                http_url="http://127.0.0.1/health",
                attempts=1,
                timeout_seconds=2,
            ),
            cwd="/srv/site",
        )

    remote_connection = CommandConnection(
        lambda _command, _cwd: OperationResult.success(
            "Ran.",
            data={
                "stdout": f"healthy\n{REMOTE_STATUS_MARKER}200",
                "stderr": "",
                "exit_status": 0,
            },
        )
    )
    remote = await HealthCheckService().run(
        remote_connection,
        HealthCheckConfig(
            http_url="http://internal/health",
            http_origin=HealthCheckOrigin.REMOTE,
            expected_substring="healthy",
            attempts=1,
        ),
        cwd="/srv/site",
    )

    assert desktop.ok
    assert desktop.data.status_code == 204
    assert remote.ok
    assert remote.data.http_ok is True
    assert "curl" in remote_connection.commands[0][0]


@pytest.mark.asyncio
async def test_deployment_lock_blocks_local_concurrency_and_reports_stale_remote_lock() -> None:
    manager = DeploymentLockManager()
    job = DeploymentJob(
        id="job-lock",
        name="Site",
        profile_id="profile-1",
        remote_target_folder="/srv/site",
    )
    success_connection = CommandConnection()
    first = await manager.acquire(success_connection, job, "run-1")
    second = await manager.acquire(success_connection, job, "run-2")
    assert first.ok
    assert not second.ok
    await manager.release(success_connection, first.data)

    owner = json.dumps({"run_id": "old", "created_at": int(time.time()) - 8000})
    stale_connection = CommandConnection(
        lambda _command, _cwd: OperationResult.success(
            "Ran.",
            data={"stdout": owner, "stderr": "", "exit_status": 73},
        )
    )
    stale = await manager.acquire(stale_connection, job, "run-3")
    assert not stale.ok
    assert stale.retryable
    assert stale.data["stale_lock"] is True


@pytest.mark.asyncio
async def test_release_prepare_restores_adopted_directory_when_clone_fails() -> None:
    calls = 0

    def responder(command: str, _cwd: str | None) -> OperationResult:
        nonlocal calls
        calls += 1
        if command.startswith("if test -L"):
            return OperationResult.success(
                "Inspected.",
                data={"stdout": "directory\n", "stderr": "", "exit_status": 0},
            )
        if "cp -a" in command:
            return OperationResult.success(
                "Failed.",
                data={"stdout": "", "stderr": "disk full", "exit_status": 1},
            )
        return OperationResult.success(
            "Ran.",
            data={"stdout": "", "stderr": "", "exit_status": 0},
        )

    connection = CommandConnection(responder)
    job = DeploymentJob(id="job-release", name="Site", remote_target_folder="/srv/site")
    result = await ReleaseManager().prepare(connection, job, "run-1")

    assert not result.ok
    assert any("mv -- '/srv/.rfm-releases/job-release/adopted-run-1' '/srv/site'" in command for command, _ in connection.commands)
    assert calls >= 5


class NoopTransferManager:
    async def cancel_batch(self, _batch_id: str) -> OperationResult:
        return OperationResult.success("Cancelled.")


class FakeLockManager:
    def __init__(self) -> None:
        self.released = False

    async def acquire(self, connection, job, run_id, *, break_stale=False) -> OperationResult:  # type: ignore[no-untyped-def]
        return OperationResult.success("Locked.", data=DeploymentLock("key", "/lock", run_id))

    async def release(self, connection, lock) -> OperationResult:  # type: ignore[no-untyped-def]
        self.released = True
        return OperationResult.success("Released.")


class ChangedPlanner:
    async def build_preview(self, job, remote_ops) -> OperationResult:  # type: ignore[no-untyped-def]
        return OperationResult.success(
            "Fresh.",
            data=DeploymentPreview(
                sync_preview=SyncPreview(total_size=1),
                target_exists=False,
                backup_directory="/backup",
                backup_archive_path="/backup/site.tar.gz",
                local_root="/tmp",
                remote_root="/srv/site",
                digest="changed",
            ),
        )


@pytest.mark.asyncio
async def test_executor_aborts_when_preview_digest_changes_under_lock(tmp_path) -> None:
    lock_manager = FakeLockManager()
    executor = DeploymentExecutor(planner=ChangedPlanner(), lock_manager=lock_manager)
    job = DeploymentJob(
        name="Site",
        profile_id="profile-1",
        local_build_folder=str(tmp_path),
        remote_target_folder="/srv/site",
    )
    preview = empty_preview(tmp_path, digest="confirmed")

    result = await executor.execute(
        job,
        preview,
        CommandConnection(),
        object(),
        NoopTransferManager(),
        policy=DeploymentExecutionPolicy(confirmed=True),
    )

    assert not result.ok
    assert result.data.preview_changed
    assert lock_manager.released


class AtomicReleaseManager:
    def __init__(self) -> None:
        self.rolled_back = False

    async def inspect_target(self, connection, job) -> OperationResult:  # type: ignore[no-untyped-def]
        return OperationResult.success("Missing.", data={"kind": "missing"})

    async def prepare(self, connection, job, run_id) -> OperationResult:  # type: ignore[no-untyped-def]
        return OperationResult.success(
            "Prepared.",
            data=AtomicReleaseContext(
                target_path="/srv/site",
                releases_root="/srv/.rfm-releases/job",
                staging_path=f"/srv/.rfm-releases/job/{run_id}.staging",
                release_path=f"/srv/.rfm-releases/job/{run_id}",
                target_was_missing=True,
            ),
        )

    async def switch(self, connection, context) -> OperationResult:  # type: ignore[no-untyped-def]
        context.switched = True
        return OperationResult.success("Switched.")

    async def rollback(self, connection, context) -> OperationResult:  # type: ignore[no-untyped-def]
        self.rolled_back = True
        return OperationResult.success("Rolled back.")

    async def prune(self, connection, job, *, active_path, previous_path) -> OperationResult:  # type: ignore[no-untyped-def]
        return OperationResult.success("Pruned.")


class FailingHealthService:
    async def run(self, connection, config, *, cwd) -> OperationResult:  # type: ignore[no-untyped-def]
        health = HealthCheckResult(ok=False, message="Unhealthy.", http_ok=False)
        result = OperationResult.failure("Unhealthy.")
        result.data = health
        return result


class EmptyTransferManager(NoopTransferManager):
    def enqueue_upload_file(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("No files should be queued.")

    async def run_until_idle(self) -> OperationResult:
        return OperationResult.success("Idle.")


@pytest.mark.asyncio
async def test_atomic_health_failure_switches_back_automatically(tmp_path) -> None:
    releases = AtomicReleaseManager()
    executor = DeploymentExecutor(
        release_manager=releases,
        health_service=FailingHealthService(),
    )
    job = DeploymentJob(
        name="Atomic",
        strategy=DeploymentStrategy.ATOMIC_RELEASE,
        local_build_folder=str(tmp_path),
        remote_target_folder="/srv/site",
        health_check=HealthCheckConfig(http_url="http://example.com"),
    )

    result = await executor.execute(
        job,
        empty_preview(tmp_path),
        CommandConnection(),
        type("RemoteOps", (), {"delete": None})(),
        EmptyTransferManager(),
        policy=DeploymentExecutionPolicy(confirmed=True),
    )

    assert not result.ok
    assert result.data.rolled_back
    assert result.data.health_check.http_ok is False
    assert releases.rolled_back
