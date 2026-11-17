"""Deployments in the web UI.

The end-to-end tests use a real AsyncSSH server that runs commands with a real POSIX shell (backups with tar,
the deployment lock, health checks), so they run where ``sh`` and ``tar`` exist with POSIX paths (Linux CI). The
validation and refusal tests run everywhere."""
from __future__ import annotations

import asyncio
import json
import queue
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

asyncssh = pytest.importorskip("asyncssh")

from app_web import bus  # noqa: E402
from app_web.api import api_post  # noqa: E402
from app_web.context import AppContext  # noqa: E402
from app_web.handlers import register_all  # noqa: E402
from core.async_runtime import AsyncRuntime  # noqa: E402

register_all()
USER, PASSWORD = "deploy", "s3cret-pass"
POSIX = sys.platform != "win32" and shutil.which("sh") is not None and shutil.which("tar") is not None
needs_posix = pytest.mark.skipif(not POSIX, reason="needs a POSIX shell and tar for the server side")


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USER and password == PASSWORD


async def _run_shell(process) -> None:  # type: ignore[no-untyped-def]
    """Exec requests run with the real shell, like on a Linux server."""
    if not process.command:
        process.exit(0)
        return
    proc = await asyncio.create_subprocess_shell(process.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    process.stdout.write(out.decode("utf-8", "replace"))
    process.stderr.write(err.decode("utf-8", "replace"))
    process.exit(proc.returncode or 0)


def _close_on_loop(server) -> None:  # type: ignore[no-untyped-def]
    async def close() -> None:
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 2)
        except asyncio.TimeoutError:
            pass

    AsyncRuntime.instance().run(close())


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
def server(tmp_path: Path):
    site = tmp_path / "srv" / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<h1>v1</h1>", encoding="utf-8")
    (site / "uploads").mkdir()
    (site / "uploads" / "photo.jpg").write_text("keep me", encoding="utf-8")

    async def start():
        key = asyncssh.generate_private_key("ssh-ed25519")
        srv = await asyncssh.create_server(_Server, "127.0.0.1", 0, server_host_keys=[key], process_factory=_run_shell,
                                           sftp_factory=True)
        return srv, srv.sockets[0].getsockname()[1]

    srv, port = AsyncRuntime.instance().run(start())
    yield site, port
    _close_on_loop(srv)


@pytest.fixture
def build(tmp_path: Path) -> Path:
    folder = tmp_path / "dist"
    folder.mkdir()
    (folder / "index.html").write_text("<h1>version 2</h1>", encoding="utf-8")
    (folder / "app.js").write_text("console.log('v2')", encoding="utf-8")
    return folder


def _connect(ctx: AppContext, port: int) -> None:
    q = bus.subscribe(500)
    try:
        assert api_post("conn.connect", {"profile": {"protocol": "ssh", "host": "127.0.0.1", "port": port, "username": USER},
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


def _until(q: queue.Queue, key: str, timeout: float = 90) -> list[dict]:  # type: ignore[type-arg]
    seen: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = json.loads(q.get(timeout=0.5))
        except queue.Empty:
            continue
        seen.append(msg)
        if msg["type"] == "task_done" and msg["payload"]["key"] == key:
            return seen
    raise AssertionError(f"{key} didn't finish; saw {[m['type'] for m in seen]}")


def _task(ctx: AppContext, api_name: str, body: dict, key: str) -> list[dict]:
    q = bus.subscribe(5000)
    try:
        reply = api_post(api_name, body, ctx)
        assert reply["ok"], reply
        seen = _until(q, key)
    finally:
        bus.unsubscribe(q)
    assert seen[-1]["payload"]["error"] is None, seen[-1]
    return seen


def _last(seen: list[dict], kind: str) -> dict:
    return [m["payload"] for m in seen if m["type"] == kind][-1]


def _job(site: Path, build: Path, **extra) -> dict:  # type: ignore[no-untyped-def]
    return {"name": "Site", "build_folder": str(build), "remote": str(site), "mode": "upload_only", "strategy": "in_place",
            "health": {"command": "test -f index.html"}, **extra}


def _preview(ctx: AppContext, job: dict) -> dict:
    return _last(_task(ctx, "deploy.preview", {"job": job}, "deploy.preview"), "deploy.preview")


# ---------------------------------------------------------------- end to end (real shell on the server)
@needs_posix
def test_deploy_backs_up_uploads_checks_and_records_history(server, ctx, build: Path) -> None:
    site, port = server
    _connect(ctx, port)
    preview = _preview(ctx, _job(site, build))
    c = preview["counts"]
    assert (c["upload"], c["replace"], c["delete"], c["same"]) == (1, 1, 0, 1)      # uploads/photo.jpg is left alone
    assert preview["target_exists"] is True and preview["backup"]
    assert (site / "index.html").read_text(encoding="utf-8") == "<h1>v1</h1>"          # a preview changes nothing

    refused = api_post("deploy.run", {"token": preview["token"]}, ctx)
    assert not refused["ok"] and "Confirm" in refused["error"]

    seen = _task(ctx, "deploy.run", {"token": preview["token"], "confirmed": True}, "deploy.run")
    result = _last(seen, "deploy.result")
    assert result["ok"], result
    assert result["health"]["ok"] is True and result["backup"]
    assert (site / "index.html").read_text(encoding="utf-8") == "<h1>version 2</h1>"
    assert (site / "uploads" / "photo.jpg").exists()                                      # upload-only keeps server files
    stages = [m["payload"]["stage"] for m in seen if m["type"] == "deploy.stage"]
    assert stages.index("locking") < stages.index("backing_up") < stages.index("transferring") < stages.index("health_check")

    history = api_post("deploy.history", {"id": result["job_id"]}, ctx)["data"]
    assert [r["status"] for r in history["runs"]] == ["success"]
    assert any(a["kind"] == "backup" for a in history["artifacts"])
    recorded = api_post("deploy.stages", {"run": history["runs"][0]["id"]}, ctx)["data"]
    assert "backing_up" in [s["stage"] for s in recorded]


@needs_posix
def test_failed_health_check_rolls_back_automatically(server, ctx, build: Path) -> None:
    site, port = server
    _connect(ctx, port)
    preview = _preview(ctx, _job(site, build, health={"command": "exit 3"}))
    result = _last(_task(ctx, "deploy.run", {"token": preview["token"], "confirmed": True}, "deploy.run"), "deploy.result")
    assert not result["ok"] and result["rolled_back"] is True
    assert (site / "index.html").read_text(encoding="utf-8") == "<h1>v1</h1>"              # the old site is back
    assert not (site / "app.js").exists()
    runs = api_post("deploy.history", {"id": result["job_id"]}, ctx)["data"]["runs"]
    assert runs[0]["status"] == "rolled_back"


@needs_posix
def test_manual_rollback_restores_an_earlier_backup(server, ctx, build: Path) -> None:
    site, port = server
    _connect(ctx, port)
    saved = api_post("deploy.save", {"job": _job(site, build)}, ctx)["data"]
    first = _preview(ctx, saved)
    assert _last(_task(ctx, "deploy.run", {"token": first["token"], "confirmed": True}, "deploy.run"), "deploy.result")["ok"]

    _task(ctx, "deploy.scan", {"id": saved["id"]}, "deploy.scan")
    backups = [a for a in api_post("deploy.history", {"id": saved["id"]}, ctx)["data"]["artifacts"] if a["kind"] == "backup"]
    assert backups
    unconfirmed = api_post("deploy.rollback", {"id": saved["id"], "artifact": backups[0]["id"]}, ctx)
    assert not unconfirmed["ok"] and "Confirm" in unconfirmed["error"]
    result = _last(_task(ctx, "deploy.rollback", {"id": saved["id"], "artifact": backups[0]["id"], "confirmed": True}, "deploy.run"),
                   "deploy.result")
    assert result["ok"] and result["kind"] == "rollback", result
    assert (site / "index.html").read_text(encoding="utf-8") == "<h1>v1</h1>"
    assert [r["action"] for r in api_post("deploy.history", {"id": saved["id"]}, ctx)["data"]["runs"]][:2] == ["manual_rollback", "deploy"]


@needs_posix
def test_nothing_is_deployed_when_the_files_changed_after_the_preview(server, ctx, build: Path) -> None:
    site, port = server
    _connect(ctx, port)
    preview = _preview(ctx, _job(site, build))
    (build / "late.css").write_text("body{}", encoding="utf-8")
    result = _last(_task(ctx, "deploy.run", {"token": preview["token"], "confirmed": True}, "deploy.run"), "deploy.result")
    assert not result["ok"] and result["preview_changed"] is True
    assert (site / "index.html").read_text(encoding="utf-8") == "<h1>v1</h1>"
    gone = api_post("deploy.run", {"token": preview["token"], "confirmed": True}, ctx)
    assert not gone["ok"] and "out of date" in gone["error"]


# ---------------------------------------------------------------- everywhere
def test_deploy_needs_a_connection_that_can_run_commands(ctx, build: Path) -> None:
    job = _job(Path("/srv/site"), build)
    reply = api_post("deploy.preview", {"job": job}, ctx)
    assert not reply["ok"] and "Connect" in reply["error"]
    ctx.session.current = SimpleNamespace(profile=SimpleNamespace(id="ftp-1", name="ftp", host="h"),
                                          capabilities=SimpleNamespace(can_exec_command=False))
    try:
        reply = api_post("deploy.preview", {"job": job}, ctx)
        assert not reply["ok"] and "SSH" in reply["error"]
    finally:
        ctx.session.current = None


@pytest.mark.parametrize(("change", "error"), [
    ({"remote": "/var"}, "protected"),
    ({"remote": "relative/path"}, "absolute"),
    ({"chmod_enabled": True, "chmod_mode": "77x"}, "octal"),
    ({"health": {"url": "file:///etc/passwd"}}, "http"),
    ({"health": {"attempts": 99}}, "between"),
    ({"backup_retention": 0}, "between"),
    ({"ignore": ["../up"]}, "plain"),
])
def test_bad_settings_are_refused(ctx, build: Path, change: dict, error: str) -> None:
    reply = api_post("deploy.save", {"job": {**_job(Path("/srv/site"), build), **change}}, ctx)
    assert not reply["ok"] and error in reply["error"].lower(), reply


def test_saved_jobs_keep_every_setting(ctx, build: Path) -> None:
    spec = _job(Path("/srv/site"), build, name="Shop", mode="mirror", strategy="atomic_release", post_command="php artisan migrate",
                restart_command="systemctl reload php-fpm", ignore="node_modules, .env", chmod_enabled=True, chmod_mode="750",
                health={"command": "true", "url": "https://shop.example.com/health", "origin": "remote", "expect": "ok",
                        "min": 200, "max": 204, "verify_tls": False})
    saved = api_post("deploy.save", {"job": spec}, ctx)["data"]
    again = next(j for j in api_post("deploy.jobs", {}, ctx)["data"]["jobs"] if j["id"] == saved["id"])
    assert again["mode"] == "mirror" and again["strategy"] == "atomic_release" and again["ignore"] == ["node_modules", ".env"]
    assert again["health"]["url"] == "https://shop.example.com/health" and again["health"]["verify_tls"] is False
    assert again["health"]["max"] == 204 and again["chmod_mode"] == "750"
    assert api_post("deploy.delete", {"id": saved["id"]}, ctx)["ok"]
    assert api_post("deploy.jobs", {}, ctx)["data"]["jobs"] == []


def test_rollback_needs_a_listed_artifact(ctx, build: Path) -> None:
    saved = api_post("deploy.save", {"job": _job(Path("/srv/site"), build)}, ctx)["data"]
    reply = api_post("deploy.rollback", {"id": saved["id"], "artifact": "nope", "confirmed": True}, ctx)
    assert not reply["ok"] and "Scan" in reply["error"]
