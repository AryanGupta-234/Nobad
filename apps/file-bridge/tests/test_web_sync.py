"""Folder sync in the web UI against a real AsyncSSH SFTP server: dry run first, skip names, confirmation before
anything is replaced or deleted, two-way sync with a baseline (changes and deletions on one side), conflict choices,
"files changed since the preview" and baselines that only apply to the folders they were taken for."""
from __future__ import annotations

import asyncio
import json
import os
import queue
import time
from pathlib import Path

import pytest

asyncssh = pytest.importorskip("asyncssh")

from app_web import bus  # noqa: E402
from app_web.api import api_post  # noqa: E402
from app_web.context import AppContext  # noqa: E402
from app_web.handlers import register_all  # noqa: E402
from app_web.sync import allowed_choices, local_manifest  # noqa: E402
from core.async_runtime import AsyncRuntime  # noqa: E402

register_all()
USER, PASSWORD = "deploy", "s3cret-pass"


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USER and password == PASSWORD


def _close_on_loop(server) -> None:  # type: ignore[no-untyped-def]
    async def close() -> None:
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 2)
        except asyncio.TimeoutError:
            pass

    AsyncRuntime.instance().run(close())


@pytest.fixture
def server(tmp_path: Path):
    root = tmp_path / "srv"
    (root / "site").mkdir(parents=True)

    async def start():
        key = asyncssh.generate_private_key("ssh-ed25519")
        srv = await asyncssh.create_server(_Server, "127.0.0.1", 0, server_host_keys=[key],
                                           sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(root)))
        return srv, srv.sockets[0].getsockname()[1]

    srv, port = AsyncRuntime.instance().run(start())
    yield root / "site", port
    _close_on_loop(srv)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    context = AppContext.create(tmp_path / "app.sqlite3")
    yield context
    context.session.disconnect()
    context.editor.shutdown()


@pytest.fixture
def local(tmp_path: Path) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    return folder


def _events(q: queue.Queue, until: str, key: str | None = None, timeout: float = 30) -> list[dict]:  # type: ignore[type-arg]
    """Collect events until ``until`` arrives (for task_done: the one with this key)."""
    seen: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = json.loads(q.get(timeout=0.5))
        except queue.Empty:
            continue
        seen.append(msg)
        if msg["type"] == until and (key is None or msg["payload"].get("key") == key):
            return seen
    raise AssertionError(f"no {until} event; saw {[m['type'] for m in seen]}")


def _connect(ctx: AppContext, port: int) -> None:
    q = bus.subscribe(500)
    try:
        assert api_post("conn.connect", {"profile": {"protocol": "sftp", "host": "127.0.0.1", "port": port, "username": USER},
                                         "secret": PASSWORD}, ctx)["ok"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                msg = json.loads(q.get(timeout=0.5))
            except queue.Empty:
                continue
            if msg["type"] == "hostkey":
                api_post("conn.trust", {"token": msg["payload"]["token"], "accept": True}, ctx)
            if msg["type"] == "connection" and msg["payload"]["status"] == "connected":
                return
        raise AssertionError("not connected")
    finally:
        bus.unsubscribe(q)


def _preview(ctx: AppContext, job: dict) -> tuple[dict, list[dict]]:
    q = bus.subscribe(2000)
    try:
        reply = api_post("sync.preview", {"job": job}, ctx)
        assert reply["ok"], reply
        seen = _events(q, "task_done", "sync.preview")
    finally:
        bus.unsubscribe(q)
    done = seen[-1]["payload"]
    assert done["error"] is None, done
    preview = [m["payload"] for m in seen if m["type"] == "sync.preview"][-1]
    entries = api_post("sync.entries", {"token": preview["token"]}, ctx)["data"]
    return preview, entries


def _run(ctx: AppContext, token: str, decisions: dict | None = None, confirmed: bool = False) -> list[dict]:
    q = bus.subscribe(5000)
    try:
        reply = api_post("sync.run", {"token": token, "decisions": decisions or {}, "confirmed": confirmed}, ctx)
        assert reply["ok"], reply
        seen = _events(q, "task_done", "sync.run", timeout=60)
    finally:
        bus.unsubscribe(q)
    assert seen[-1]["payload"]["error"] is None, seen[-1]
    return seen


def _result(seen: list[dict]) -> dict:
    return [m["payload"] for m in seen if m["type"] == "sync.result"][-1]


def _by_path(entries: list[dict]) -> dict[str, dict]:
    return {e["path"]: e for e in entries}


def test_upload_dry_run_then_sync_skips_named_folders(server, ctx, local: Path) -> None:
    remote, port = server
    (local / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (local / "css").mkdir()
    (local / "css" / "site.css").write_text("body{}", encoding="utf-8")
    (local / "node_modules" / "pkg").mkdir(parents=True)
    (local / "node_modules" / "pkg" / "x.js").write_text("x", encoding="utf-8")
    _connect(ctx, port)
    job = {"name": "Site", "mode": "local_to_remote", "local": str(local), "remote": "/site"}

    preview, entries = _preview(ctx, job)
    assert preview["counts"]["upload"] == 2 and preview["needs_confirm"] is False
    assert set(_by_path(entries)) == {"index.html", "css/site.css"}            # node_modules never listed
    assert not any(remote.iterdir())                                           # a preview changes nothing

    result = _result(_run(ctx, preview["token"]))
    assert result["ok"] and result["copied"] == 2
    assert (remote / "css" / "site.css").read_text(encoding="utf-8") == "body{}"
    assert not (remote / "node_modules").exists()

    again = api_post("sync.run", {"token": preview["token"]}, ctx)              # a token is used once
    assert not again["ok"] and "out of date" in again["error"]


def test_replacing_or_deleting_needs_confirmation(server, ctx, local: Path) -> None:
    remote, port = server
    (local / "app.js").write_text("v2 with more text", encoding="utf-8")
    (remote / "app.js").write_text("v1", encoding="utf-8")
    (remote / "old.js").write_text("stale", encoding="utf-8")
    _connect(ctx, port)
    preview, entries = _preview(ctx, {"mode": "local_to_remote", "local": str(local), "remote": "/site"})
    rows = _by_path(entries)
    assert rows["app.js"]["action"] == "overwrite" and rows["old.js"]["action"] == "delete"
    assert preview["needs_confirm"] is True

    refused = api_post("sync.run", {"token": preview["token"]}, ctx)
    assert not refused["ok"] and "Confirm" in refused["error"]
    assert (remote / "old.js").exists()

    result = _result(_run(ctx, preview["token"], confirmed=True))
    assert result["ok"] and result["deleted_remote"] == 1
    assert (remote / "app.js").read_text(encoding="utf-8") == "v2 with more text" and not (remote / "old.js").exists()


def test_two_way_with_baseline_follows_changes_and_deletions(server, ctx, local: Path) -> None:
    remote, port = server
    (local / "notes.md").write_text("mine", encoding="utf-8")
    (remote / "report.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    _connect(ctx, port)
    saved = api_post("sync.save", {"job": {"name": "Both", "mode": "two_way", "local": str(local), "remote": "/site"}}, ctx)
    assert saved["ok"], saved
    job = {**saved["data"], "mode": "two_way"}

    first, entries = _preview(ctx, job)
    rows = _by_path(entries)
    assert rows["notes.md"]["action"] == "upload" and rows["report.csv"]["action"] == "download"
    assert first["baseline"] is False
    assert _result(_run(ctx, first["token"]))["baseline"] is True
    assert (remote / "notes.md").exists() and (local / "report.csv").exists()

    # now one side deletes, the other side edits: both changes cross over, nothing is a conflict
    (local / "notes.md").unlink()
    (remote / "report.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    second, entries = _preview(ctx, job)
    rows = _by_path(entries)
    assert second["baseline"] is True and second["counts"]["conflict"] == 0
    assert rows["notes.md"]["action"] == "delete" and rows["report.csv"]["action"] == "download"
    _run(ctx, second["token"], confirmed=True)
    assert not (remote / "notes.md").exists()
    assert (local / "report.csv").read_text(encoding="utf-8") == "a,b\n1,2\n3,4\n"


def test_two_way_conflicts_need_a_possible_choice(server, ctx, local: Path) -> None:
    remote, port = server
    (local / "config.ini").write_text("[app]\ndebug = true\n", encoding="utf-8")
    (remote / "config.ini").write_text("[app]\ndebug = false\ncache = 600\n", encoding="utf-8")
    _connect(ctx, port)
    preview, entries = _preview(ctx, {"mode": "two_way", "local": str(local), "remote": "/site"})
    row = _by_path(entries)["config.ini"]
    assert row["action"] == "conflict" and set(row["choices"]) == {"use_local", "use_remote", "keep_both", "skip"}

    diff = api_post("sync.compare", {"token": preview["token"], "path": "config.ini"}, ctx)["data"]
    assert "debug = true" in diff["local"] and "cache = 600" in diff["remote"]

    missing = api_post("sync.run", {"token": preview["token"], "decisions": {}}, ctx)
    assert not missing["ok"] and "conflicting file" in missing["error"]
    bogus = api_post("sync.run", {"token": preview["token"], "decisions": {"config.ini": "launch"}, "confirmed": True}, ctx)
    assert not bogus["ok"]

    _run(ctx, preview["token"], {"config.ini": "keep_both"}, confirmed=True)
    kept = [p.name for p in remote.iterdir() if p.name.startswith("config.remote-conflict-")]
    assert len(kept) == 1 and "cache = 600" in (remote / kept[0]).read_text(encoding="utf-8")
    assert (remote / "config.ini").read_text(encoding="utf-8") == "[app]\ndebug = true\n"     # mine is canonical
    assert (local / kept[0]).exists()                                                        # both sides keep both


def test_nothing_runs_when_files_changed_after_the_preview(server, ctx, local: Path) -> None:
    remote, port = server
    (local / "a.txt").write_text("a", encoding="utf-8")
    _connect(ctx, port)
    preview, _entries = _preview(ctx, {"mode": "local_to_remote", "local": str(local), "remote": "/site"})
    (local / "b.txt").write_text("arrived later", encoding="utf-8")
    seen = _run(ctx, preview["token"])
    fresh = [m["payload"] for m in seen if m["type"] == "sync.preview"][-1]
    assert fresh["changed"] is True and fresh["counts"]["upload"] == 2
    assert not [m for m in seen if m["type"] == "sync.result"]
    assert not (remote / "a.txt").exists()                                     # nothing was copied


def test_a_baseline_only_counts_for_its_own_folders(server, ctx, local: Path, tmp_path: Path) -> None:
    remote, port = server
    (local / "same.txt").write_text("x", encoding="utf-8")
    _connect(ctx, port)
    job = api_post("sync.save", {"job": {"name": "B", "mode": "two_way", "local": str(local), "remote": "/site"}}, ctx)["data"]
    first, _ = _preview(ctx, job)
    _run(ctx, first["token"])
    other = tmp_path / "elsewhere"
    other.mkdir()
    moved = api_post("sync.save", {"job": {**job, "local": str(other)}}, ctx)["data"]
    preview, entries = _preview(ctx, moved)
    assert preview["baseline"] is False                                       # the old baseline doesn't apply
    assert _by_path(entries)["same.txt"]["action"] == "download"              # not "deleted locally"

    assert api_post("sync.delete", {"id": job["id"]}, ctx)["ok"]
    assert api_post("sync.jobs", {}, ctx)["data"]["jobs"] == []


def test_conflict_choices_match_what_exists() -> None:
    both, here, there = {"f": 1}, {"f": 1}, {"f": 1}
    assert allowed_choices("f", both, there) == {"use_local", "use_remote", "keep_both", "skip"}
    assert allowed_choices("f", here, {}) == {"use_local", "skip"}
    assert allowed_choices("f", {}, there) == {"use_remote", "skip"}


def test_local_listing_never_follows_links(tmp_path: Path) -> None:
    import threading

    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    (root / "real.txt").write_text("y", encoding="utf-8")
    try:
        os.symlink(outside, root / "linked", target_is_directory=True)
        os.symlink(outside / "secret.txt", root / "file-link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("creating links needs extra rights here")
    assert [e.path for e in local_manifest(root, None, threading.Event())] == ["real.txt"]


def test_sync_needs_a_connection_and_valid_job(ctx, local: Path) -> None:
    no_conn = api_post("sync.preview", {"job": {"mode": "two_way", "local": str(local), "remote": "/site"}}, ctx)
    assert not no_conn["ok"] and "Connect" in no_conn["error"]
    bad_mode = api_post("sync.preview", {"job": {"mode": "sideways", "local": str(local), "remote": "/x"}}, ctx)
    assert not bad_mode["ok"]
    bad_skip = api_post("sync.save", {"job": {"mode": "two_way", "local": str(local), "remote": "/x", "ignore": ["../etc"]}}, ctx)
    assert not bad_skip["ok"]
