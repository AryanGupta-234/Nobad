"""Tunnels and live logs in the web UI against a real AsyncSSH server: a local forward that really carries bytes
to an echo service, network-exposure guards, closing with the connection, and log streams over real exec channels
(lines batched to the page, a missing file and a sudo password prompt reported with their reason)."""
from __future__ import annotations

import asyncio
import json
import queue
import socket
import time
from pathlib import Path

import pytest

asyncssh = pytest.importorskip("asyncssh")

from app_web import bus  # noqa: E402
from app_web.api import api_post  # noqa: E402
from app_web.context import AppContext  # noqa: E402
from app_web.handlers import register_all  # noqa: E402
from core.async_runtime import AsyncRuntime  # noqa: E402
from core.tunnel_manager import SSHTunnelManager  # noqa: E402

register_all()
USER, PASSWORD = "deploy", "s3cret-pass"
LOG_LINES = ['192.0.2.7 - - [17/Nov/2026:10:00:01 +0000] "GET / HTTP/1.1" 200 512 "-" "curl"',
             '192.0.2.7 - - [17/Nov/2026:10:00:02 +0000] "GET /missing HTTP/1.1" 404 120 "-" "curl"',
             "2026/11/17 10:00:03 [error] 811#811: *9 connect() failed (111: Connection refused) while connecting to upstream"]


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USER and password == PASSWORD

    def connection_requested(self, dest_host, dest_port, orig_host, orig_port):  # type: ignore[no-untyped-def]
        return True

    def server_requested(self, listen_host, listen_port):  # type: ignore[no-untyped-def]
        return True


async def _process(process) -> None:  # type: ignore[no-untyped-def]
    """Acts like tail/journalctl for the commands the app sends."""
    cmd = process.command or ""
    if cmd.startswith("sudo -n "):
        process.stderr.write("sudo: a password is required\n")
        process.exit(1)
        return
    if "/var/log/nope.log" in cmd:
        process.stderr.write("tail: cannot open '/var/log/nope.log' for reading: No such file or directory\n")
        process.exit(1)
        return
    if cmd.startswith("tail ") or cmd.startswith("journalctl "):
        for line in LOG_LINES:
            process.stdout.write(line + "\n")
        try:
            while True:                                   # -F: keep following until stopped
                await asyncio.sleep(0.2)
                process.stdout.write('192.0.2.9 - - [17/Nov/2026:10:00:09 +0000] "GET /health HTTP/1.1" 200 2 "-" "probe"\n')
        except (asyncio.CancelledError, BrokenPipeError, ConnectionError, asyncssh.Error):
            return
    process.exit(0)


def _close_on_loop(server) -> None:  # type: ignore[no-untyped-def]
    async def close() -> None:
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 2)
        except asyncio.TimeoutError:
            pass

    AsyncRuntime.instance().run(close())


@pytest.fixture
def ssh_port(tmp_path: Path):
    async def start():
        key = asyncssh.generate_private_key("ssh-ed25519")
        srv = await asyncssh.create_server(_Server, "127.0.0.1", 0, server_host_keys=[key], process_factory=_process,
                                           sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(tmp_path)))
        return srv, srv.sockets[0].getsockname()[1]

    srv, port = AsyncRuntime.instance().run(start())
    yield port
    _close_on_loop(srv)


@pytest.fixture
def echo_port():
    """A service on the 'server side' (here: this machine) that echoes what it gets, upper-cased."""
    async def handle(reader, writer):  # type: ignore[no-untyped-def]
        data = await reader.read(100)
        writer.write(data.upper())
        await writer.drain()
        writer.close()

    async def start():
        srv = await asyncio.start_server(handle, "127.0.0.1", 0)
        return srv, srv.sockets[0].getsockname()[1]

    srv, port = AsyncRuntime.instance().run(start())
    yield port
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
    time.sleep(0.3)


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


def _free_port() -> int:
    return SSHTunnelManager.find_next_available_port(20000 + int(time.time() * 1000) % 20000)


def _talk(port: int, text: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(text)
        return s.recv(100)


# ---------------------------------------------------------------- tunnels
def test_local_forward_carries_traffic_and_closes_with_the_connection(ssh_port, echo_port, ctx) -> None:
    _connect(ctx, ssh_port)
    local = _free_port()
    saved = api_post("tunnel.save", {"tunnel": {"name": "Echo", "type": "local", "local_port": local, "remote_port": echo_port}}, ctx)
    assert saved["ok"], saved
    started = api_post("tunnel.start", {"id": saved["data"]["id"]}, ctx)
    assert started["ok"], started
    assert _talk(local, b"hello") == b"HELLO"                         # bytes really go through the SSH tunnel
    listing = api_post("tunnel.list", {}, ctx)["data"]["tunnels"][0]
    assert listing["status"] == "active" and listing["ssh"].startswith("ssh -N -L 127.0.0.1:")
    assert api_post("tunnel.test", {"id": saved["data"]["id"]}, ctx)["data"]["ok"] is True

    api_post("conn.disconnect", {}, ctx)
    # The listener is gone: connecting is refused. (A bind test would see the port "in use" on Linux while our own
    # finished connections sit in TIME_WAIT.)
    deadline, refused = time.monotonic() + 10, False
    while time.monotonic() < deadline and not refused:
        try:
            socket.create_connection(("127.0.0.1", local), timeout=1).close()
            time.sleep(0.2)
        except OSError:
            refused = True
    assert refused
    assert api_post("tunnel.list", {}, ctx)["data"]["tunnels"][0]["status"] == "inactive"


def test_busy_ports_are_refused_with_a_suggestion(ssh_port, echo_port, ctx) -> None:
    _connect(ctx, ssh_port)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        busy = taken.getsockname()[1]
        saved = api_post("tunnel.save", {"tunnel": {"type": "local", "local_port": busy, "remote_port": echo_port}}, ctx)["data"]
        reply = api_post("tunnel.start", {"id": saved["id"]}, ctx)
    assert not reply["ok"] and "already in use" in reply["error"] and "Choose a different local port" in reply["error"]


@pytest.mark.parametrize(("spec", "error"), [
    ({"type": "socks5", "local_host": "0.0.0.0", "local_port": 1080}, "other devices"),
    ({"type": "local", "local_host": "192.168.1.20", "local_port": 8080, "remote_port": 80}, "other devices"),
    ({"type": "remote", "remote_host": "0.0.0.0", "remote_port": 8080, "local_port": 3000}, "from anywhere"),
    ({"type": "local", "local_port": 70000, "remote_port": 80}, "between"),
    ({"type": "local", "local_port": 8080, "remote_host": "db; rm -rf /", "remote_port": 5432}, "valid host"),
])
def test_exposing_a_tunnel_needs_an_explicit_choice(ctx, spec: dict, error: str) -> None:
    reply = api_post("tunnel.save", {"tunnel": spec}, ctx)
    assert not reply["ok"] and error in reply["error"], reply
    allowed = api_post("tunnel.save", {"tunnel": {**spec, "allow_lan": True, "allow_public": True}}, ctx)
    assert allowed["ok"] is (error in {"other devices", "from anywhere"})


# ---------------------------------------------------------------- live logs
def _lines(q: queue.Queue, sid: str, want: int, timeout: float = 10) -> list[dict]:  # type: ignore[type-arg]
    rows: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(rows) < want and time.monotonic() < deadline:
        try:
            msg = json.loads(q.get(timeout=0.3))
        except queue.Empty:
            continue
        if msg["type"] == "logs.lines" and msg["payload"]["id"] == sid:
            rows.extend(msg["payload"]["rows"])
    return rows


def test_a_log_streams_in_batches_and_stops(ssh_port, ctx) -> None:
    _connect(ctx, ssh_port)
    q = bus.subscribe(2000)
    try:
        started = api_post("logs.start", {"log": {"source": "file", "path": "/var/log/nginx/access.log"}}, ctx)
        assert started["ok"], started
        sid = started["data"]["id"]
        rows = _lines(q, sid, 4)
    finally:
        bus.unsubscribe(q)
    assert [r["status"] for r in rows[:2]] == [200, 404]
    assert rows[2]["lvl"] == "error"
    assert len(api_post("logs.tail", {"id": sid}, ctx)["data"]) >= 4
    assert api_post("logs.stop", {"id": sid}, ctx)["ok"]
    assert api_post("logs.list", {}, ctx)["data"]["streams"][0]["status"] == "stopped"


@pytest.mark.parametrize(("spec", "reason"), [
    ({"source": "file", "path": "/var/log/nope.log"}, "No such file"),
    ({"source": "file", "path": "/var/log/auth.log", "sudo": True}, "asks for a password"),
])
def test_a_log_that_ends_by_itself_says_why(ssh_port, ctx, spec: dict, reason: str) -> None:
    _connect(ctx, ssh_port)
    sid = api_post("logs.start", {"log": spec}, ctx)["data"]["id"]
    deadline = time.monotonic() + 10
    stream = {}
    while time.monotonic() < deadline:
        stream = next(s for s in api_post("logs.list", {}, ctx)["data"]["streams"] if s["id"] == sid)
        if stream["status"] == "error":
            break
        time.sleep(0.2)
    assert stream["status"] == "error" and reason in (stream["error"] or ""), stream


@pytest.mark.parametrize("spec", [
    {"source": "file", "path": "relative.log"},
    {"source": "file", "path": "/var/log/x\nrm -rf /"},
    {"source": "journal", "unit": "nginx; reboot"},
    {"source": "pipe", "path": "/x"},
])
def test_bad_log_sources_are_refused(ssh_port, ctx, spec: dict) -> None:
    _connect(ctx, ssh_port)
    assert not api_post("logs.start", {"log": spec}, ctx)["ok"]
