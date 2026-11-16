from __future__ import annotations

import asyncio

import pytest

from deployment.local_build_runner import LocalBuildRunner


@pytest.mark.asyncio
async def test_local_build_streams_redacted_output(tmp_path) -> None:
    lines: list[str] = []

    result = await LocalBuildRunner().run(
        "printf 'password=hunter2\\nbuild complete\\n'",
        working_directory=tmp_path,
        on_output=lines.append,
    )

    assert result.ok
    assert lines == ["password=<redacted>", "build complete"]


@pytest.mark.asyncio
async def test_local_build_failure_stops_before_deployment(tmp_path) -> None:
    result = await LocalBuildRunner().run(
        "printf 'failed\\n'; exit 7",
        working_directory=tmp_path,
    )

    assert not result.ok
    assert "status 7" in result.message


@pytest.mark.asyncio
async def test_local_build_can_be_cancelled(tmp_path) -> None:
    runner = LocalBuildRunner()
    task = asyncio.create_task(
        runner.run(
            "sleep 30",
            working_directory=tmp_path,
        )
    )
    await asyncio.sleep(0.05)

    await runner.cancel()
    result = await asyncio.wait_for(task, timeout=2)

    assert not result.ok
