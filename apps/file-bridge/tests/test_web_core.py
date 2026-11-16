"""Web UI building blocks: secret scrubbing, event coalescing, long tasks and the shared settings rows."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import pytest

from app_web import bus, tasks
from app_web.settings_store import FIELDS, SettingError, SettingsStore, coerce
from core.async_runtime import AsyncRuntime
from storage.app_data import AppDataService


# ---------------------------------------------------------------- scrub
@pytest.mark.parametrize(("text", "secret"), [
    ("password=hunter2 for deploy", "hunter2"),
    ('{"token": "abc.def.ghi"}', "abc.def.ghi"),
    ("api_key: sk-live-123", "sk-live-123"),
    ("sftp://deploy:s3cret@example.com/var/www", "s3cret"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----", "AAAA"),
])
def test_scrub_hides_secrets(text: str, secret: str) -> None:
    cleaned = bus.scrub(text)
    assert secret not in cleaned
    assert "(hidden" in cleaned


def test_scrub_leaves_plain_text_alone() -> None:
    assert bus.scrub("Uploaded index.html to /var/www (12 KB)") == "Uploaded index.html to /var/www (12 KB)"


def test_log_lines_are_scrubbed_and_broadcast() -> None:
    q = bus.subscribe()
    try:
        entry = bus.log("Login failed: password=hunter2", "bad", "ssh")
        message = q.get(timeout=2)
    finally:
        bus.unsubscribe(q)
    assert "hunter2" not in entry["msg"] and "hunter2" not in message
    assert bus.recent_log()[-1] == entry


# ---------------------------------------------------------------- coalescer
def test_coalescer_sends_only_the_latest_payload_per_key() -> None:
    sent: list[tuple[str, object]] = []
    c = bus.Coalescer("progress", interval=0.05, send=lambda kind, payload: sent.append((kind, payload)))
    for done in range(100):
        c.push("job-1", {"id": "job-1", "done": done})
    c.push("job-2", {"id": "job-2", "done": 7})
    time.sleep(0.2)

    assert sent == [("progress", [{"id": "job-1", "done": 99}, {"id": "job-2", "done": 7}])]


# ---------------------------------------------------------------- tasks
def _wait_for(q: "queue.Queue[str]", kind: str) -> dict:
    import json

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        msg = json.loads(q.get(timeout=5))
        if msg["type"] == kind:
            return msg["payload"]
    raise AssertionError(f"no {kind} event")


def test_task_reports_done_and_refuses_a_second_run_while_busy() -> None:
    q = bus.subscribe()
    release = threading.Event()
    results: list[object] = []

    async def work() -> str:
        while not release.is_set():
            import asyncio

            await asyncio.sleep(0.01)
        return "finished"

    try:
        assert tasks.run_task("test.busy", work, on_result=results.append, runtime=AsyncRuntime.instance())
        assert tasks.run_task("test.busy", work) is False
        release.set()
        done = _wait_for(q, "task_done")
    finally:
        bus.unsubscribe(q)
    assert done == {"key": "test.busy", "error": None}
    assert results == ["finished"]
    assert not tasks.is_running("test.busy")


def test_a_crashing_task_still_reports_task_done_with_a_scrubbed_error() -> None:
    q = bus.subscribe()

    async def work() -> None:
        raise RuntimeError("auth failed, password=hunter2")

    try:
        tasks.run_task("test.crash", work)
        done = _wait_for(q, "task_done")
    finally:
        bus.unsubscribe(q)
    assert done["key"] == "test.crash"
    assert "auth failed" in done["error"] and "hunter2" not in done["error"]


# ---------------------------------------------------------------- settings
def test_web_settings_share_the_rows_the_qt_ui_reads(tmp_path: Path) -> None:
    app_data = AppDataService.create(tmp_path / "app.sqlite3")
    with app_data.session_factory() as session:      # what the Qt UI saved earlier
        app_data.settings(session).set("terminal", {"value": {"font_size": 13, "profiles": [{"name": "Default Shell"}]}})
        session.commit()

    store = SettingsStore(app_data)
    store.set("terminal.font_size", 18)
    store.set("transfer.max_concurrent", 5)

    with app_data.session_factory() as session:
        repo = app_data.settings(session)
        terminal = repo.get("terminal")["value"]
        concurrency = repo.get("transfer.max_concurrent")["value"]
    assert terminal == {"font_size": 18, "profiles": [{"name": "Default Shell"}]}   # other keys kept
    assert concurrency == 5


def test_every_setting_default_passes_its_own_validation() -> None:
    for spec in FIELDS:
        assert coerce(spec, spec.default) == spec.default


@pytest.mark.parametrize("value", ["two\nlines", "nul\0byte", "x" * 300, 5])
def test_text_settings_refuse_unsafe_values(value: object) -> None:
    spec = next(f for f in FIELDS if f.id == "tools.rsync_path")
    with pytest.raises(SettingError):
        coerce(spec, value)


def test_a_corrupt_stored_value_falls_back_to_the_default(tmp_path: Path) -> None:
    app_data = AppDataService.create(tmp_path / "app.sqlite3")
    with app_data.session_factory() as session:
        app_data.settings(session).set("transfer.max_concurrent", {"value": "lots"})
        session.commit()
    assert SettingsStore(app_data).get("transfer.max_concurrent") == 3
