"""End to end against a real SFTP server (AsyncSSH, on 127.0.0.1, chrooted to a temp folder), through the same API
calls the web UI makes: host-key prompt and trust, connect, list, mkdir/rename/delete, upload, conflict plan,
download, disconnect. Nothing touches the developer's real home folder or known_hosts."""
from __future__ import annotations

import json
import queue
import time
from pathlib import Path

import pytest

asyncssh = pytest.importorskip("asyncssh")

from app_web import bus  # noqa: E402
from app_web.api import api_post  # noqa: E402
from app_web.context import AppContext  # noqa: E402
from app_web.handlers import register_all  # noqa: E402
from core.async_runtime import AsyncRuntime  # noqa: E402

USER, PASSWORD = "deploy", "s3cret-pass"
register_all()


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USER and password == PASSWORD


@pytest.fixture
def sftp_server(tmp_path: Path):
    root = tmp_path / "server-root"
    (root / "site").mkdir(parents=True)
    (root / "site" / "index.html").write_text("<h1>hello</h1>", encoding="utf-8")

    async def start():
        key = asyncssh.generate_private_key("ssh-ed25519")
        server = await asyncssh.create_server(
            _Server, "127.0.0.1", 0, server_host_keys=[key],
            sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(root)),
        )
        return server, server.sockets[0].getsockname()[1]

    server, port = AsyncRuntime.instance().run(start())
    yield root, port
    server.close()


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)       # known_hosts and data stay in the test folder
    return AppContext.create(tmp_path / "app.sqlite3")


def wait_for(q: "queue.Queue[str]", kind: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = json.loads(q.get(timeout=0.5))
        except queue.Empty:
            continue
        if msg["type"] == kind:
            return msg["payload"]
    raise AssertionError(f"no {kind} event")


def wait_connected(q: "queue.Queue[str]") -> None:
    """Until the connect task has finished with a connection (the first event only says "connecting")."""
    connected = False
    while True:
        msg_kind, payload = _next(q)
        if msg_kind == "connection" and payload["status"] == "connected":
            connected = True
        if msg_kind == "task_done" and payload["key"] == "conn.connect" and connected:
            return


def _next(q: "queue.Queue[str]", timeout: float = 20.0) -> tuple[str, dict]:
    msg = json.loads(q.get(timeout=timeout))
    return msg["type"], msg["payload"]


def call(ctx: AppContext, api_name: str, **body) -> dict:
    reply = api_post(api_name, body, ctx)
    assert reply["ok"], reply
    return reply.get("data")


def test_connect_browse_transfer_and_disconnect(sftp_server, ctx, tmp_path: Path) -> None:
    root, port = sftp_server
    events = bus.subscribe(2000)
    try:
        # 1. unknown host key: connecting stops and asks
        call(ctx, "conn.connect", profile={"protocol": "sftp", "host": "127.0.0.1", "port": port, "username": USER},
             secret=PASSWORD, save=True, remember=False)
        prompt = wait_for(events, "hostkey")
        assert prompt["fingerprint"].startswith("SHA256:") and prompt["changed"] is False
        assert ctx.session.state()["status"] == "disconnected"

        # 2. a wrong or reused token does nothing
        assert not api_post("conn.trust", {"token": "nope", "accept": True}, ctx)["ok"]

        # 3. trust -> reconnects -> connected; the profile is saved without the password
        call(ctx, "conn.trust", token=prompt["token"], accept=True)
        state = wait_for(events, "connection")
        while state["status"] != "connected":
            state = wait_for(events, "connection")
        assert state["profile"]["host"] == "127.0.0.1"
        assert not api_post("conn.trust", {"token": prompt["token"], "accept": True}, ctx)["ok"]
        profiles = call(ctx, "conn.profiles")
        assert len(profiles) == 1 and profiles[0]["secret_saved"] is False
        assert (Path.home() / ".remote-file-manager" / "known_hosts").read_text().strip()

        # 4. browse
        listing = call(ctx, "fs.remote.list", path="/site")
        assert [i[0] for i in listing["items"]] == ["index.html"]
        assert listing["parent"] == "/"

        # 5. mkdir / rename / delete on the server
        call(ctx, "fs.remote.mkdir", folder="/site", name="assets")
        call(ctx, "fs.remote.rename", path="/site/assets", name="static")
        assert (root / "site" / "static").is_dir()
        assert not api_post("fs.remote.mkdir", {"folder": "/site", "name": "../escape"}, ctx)["ok"]
        call(ctx, "fs.remote.delete", path="/site/static", recursive=True)
        assert not (root / "site" / "static").exists()

        # 6. upload, then the same upload is a conflict, then "keep both" renames
        local = tmp_path / "local"
        local.mkdir()
        (local / "app.js").write_text("console.log(1)", encoding="utf-8")
        assert call(ctx, "xfer.plan", direction="upload", items=[str(local / "app.js")], dest="/site")["conflicts"] == []
        call(ctx, "xfer.start", direction="upload", items=[str(local / "app.js")], dest="/site", policy=None)
        wait_for(events, "xfer.batch_done")
        assert (root / "site" / "app.js").read_text(encoding="utf-8") == "console.log(1)"
        conflicts = call(ctx, "xfer.plan", direction="upload", items=[str(local / "app.js")], dest="/site")["conflicts"]
        assert [c["name"] for c in conflicts] == ["app.js"]
        call(ctx, "xfer.start", direction="upload", items=[str(local / "app.js")], dest="/site", policy="rename")
        wait_for(events, "xfer.batch_done")
        assert len(list((root / "site").glob("app*.js"))) == 2

        # 7. download a folder
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        call(ctx, "xfer.start", direction="download", items=["/site"], dest=str(downloads), policy=None)
        done = wait_for(events, "xfer.batch_done")
        assert done["failed"] == 0
        assert (downloads / "site" / "index.html").read_text(encoding="utf-8") == "<h1>hello</h1>"
        jobs = call(ctx, "xfer.list")
        assert jobs and all(j["status"] == "completed" for j in jobs)
        assert all(PASSWORD not in json.dumps(j) for j in jobs)

        # 8. disconnect
        call(ctx, "conn.disconnect")
        assert ctx.session.state()["status"] == "disconnected"
        assert not api_post("fs.remote.list", {"path": "/"}, ctx)["ok"]
    finally:
        bus.unsubscribe(events)


def test_declining_the_host_key_does_not_connect_or_save_it(sftp_server, ctx) -> None:
    _root, port = sftp_server
    events = bus.subscribe(500)
    try:
        call(ctx, "conn.connect", profile={"protocol": "sftp", "host": "127.0.0.1", "port": port, "username": USER},
             secret=PASSWORD)
        prompt = wait_for(events, "hostkey")
        call(ctx, "conn.trust", token=prompt["token"], accept=False)
        assert ctx.session.state()["status"] == "disconnected"
        known = Path.home() / ".remote-file-manager" / "known_hosts"
        assert not known.exists() or not known.read_text().strip()
    finally:
        bus.unsubscribe(events)


def test_wrong_password_reports_a_plain_error(sftp_server, ctx) -> None:
    _root, port = sftp_server
    events = bus.subscribe(500)
    try:
        call(ctx, "conn.connect", profile={"protocol": "sftp", "host": "127.0.0.1", "port": port, "username": USER},
             secret=PASSWORD)
        call(ctx, "conn.trust", token=wait_for(events, "hostkey")["token"], accept=True)
        wait_connected(events)
        call(ctx, "conn.disconnect")
        while wait_for(events, "task_done")["key"] != "conn.disconnect":
            pass
        call(ctx, "conn.connect", profile={"protocol": "sftp", "host": "127.0.0.1", "port": port, "username": USER},
             secret="wrong-password")
        failed = wait_for(events, "conn_failed")
        assert failed["message"] and "wrong-password" not in json.dumps(failed)
    finally:
        bus.unsubscribe(events)


@pytest.mark.parametrize("profile, error", [
    ({"protocol": "telnet", "host": "x", "username": "u"}, "Choose SFTP"),
    ({"protocol": "sftp", "host": "bad host name", "username": "u"}, "Host"),
    ({"protocol": "sftp", "host": "example.com", "port": 70000, "username": "u"}, "Port"),
    ({"protocol": "sftp", "host": "example.com", "username": ""}, "Username"),
    ({"protocol": "sftp", "host": "example.com", "username": "u", "auth_type": "ssh_key"}, "key file"),
])
def test_bad_connection_forms_are_refused(ctx, profile: dict, error: str) -> None:
    reply = api_post("conn.connect", {"profile": profile, "secret": "x"}, ctx)
    assert not reply["ok"] and error in reply["error"]


def test_a_page_that_reloads_still_gets_the_open_host_key_question(sftp_server, ctx) -> None:
    _root, port = sftp_server
    events = bus.subscribe(500)
    try:
        call(ctx, "conn.connect", profile={"protocol": "sftp", "host": "127.0.0.1", "port": port, "username": USER},
             secret=PASSWORD)
        prompt = wait_for(events, "hostkey")
        state = call(ctx, "conn.state")                  # what a freshly loaded page asks first
        assert state["hostkey"]["token"] == prompt["token"]
        assert state["hostkey"]["fingerprint"] == prompt["fingerprint"]
        call(ctx, "conn.trust", token=prompt["token"], accept=False)
        assert "hostkey" not in call(ctx, "conn.state")
    finally:
        bus.unsubscribe(events)
