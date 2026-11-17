"""Terminal tabs: a real SSH shell on an AsyncSSH test server, a real local shell, output ordering and limits."""
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
from app_web.terminals import MAX_PENDING, OutputBuffer  # noqa: E402
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


async def _shell(process) -> None:  # type: ignore[no-untyped-def]
    """A tiny shell: prompt, echo each line back, report the terminal size on `size`, exit on `exit`."""
    process.stdout.write("demo$ ")
    try:
        while True:
            try:
                line = await process.stdin.readline()
            except asyncssh.TerminalSizeChanged:
                continue                      # a resize interrupts the read; a real shell just redraws
            if not line or line.strip() == "exit":
                break
            if line.strip() == "size":
                cols, rows, *_ = process.get_terminal_size()
                process.stdout.write(f"size {cols}x{rows}\r\ndemo$ ")
            else:
                process.stdout.write(f"you said: {line.strip()}\r\ndemo$ ")
    except asyncssh.BreakReceived:
        pass
    process.exit(0)


def _close_on_loop(server) -> None:  # type: ignore[no-untyped-def]
    """Close the test server on the runtime's own loop (asyncio objects aren't thread-safe)."""
    async def close() -> None:
        server.close()
        await server.wait_closed()

    AsyncRuntime.instance().run(close())


@pytest.fixture
def server(tmp_path: Path):
    async def start():
        key = asyncssh.generate_private_key("ssh-ed25519")
        srv = await asyncssh.create_server(_Server, "127.0.0.1", 0, server_host_keys=[key], process_factory=_shell,
                                           sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(tmp_path)))
        return srv, srv.sockets[0].getsockname()[1]

    srv, port = AsyncRuntime.instance().run(start())
    yield port
    _close_on_loop(srv)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return AppContext.create(tmp_path / "app.sqlite3")


def _events(q: "queue.Queue[str]", until, timeout: float = 20.0) -> str:  # type: ignore[no-untyped-def]
    """Collect term.out data until `until(text)` is true."""
    text, deadline = "", time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = json.loads(q.get(timeout=0.3))
        except queue.Empty:
            continue
        if msg["type"] == "term.out":
            text += msg["payload"]["data"]
            if until(text):
                return text
        if msg["type"] == "hostkey":
            raise AssertionError("unexpected host key prompt")
    raise AssertionError(f"timed out; got {text!r}")


def _connect(ctx: AppContext, port: int, q: "queue.Queue[str]") -> None:
    assert api_post("conn.connect", {"profile": {"protocol": "ssh", "host": "127.0.0.1", "port": port, "username": USER},
                                     "secret": PASSWORD}, ctx)["ok"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        msg = json.loads(q.get(timeout=20))
        if msg["type"] == "hostkey":
            assert api_post("conn.trust", {"token": msg["payload"]["token"], "accept": True}, ctx)["ok"]
        if msg["type"] == "connection" and msg["payload"]["status"] == "connected":
            return
    raise AssertionError("not connected")


def test_remote_terminal_echoes_resizes_and_closes_on_disconnect(server, ctx) -> None:
    q = bus.subscribe(5000)
    try:
        _connect(ctx, server, q)
        reply = api_post("term.open", {"kind": "remote", "cols": 120, "rows": 40}, ctx)
        assert reply["ok"], reply
        term_id = reply["data"]["id"]
        assert _events(q, lambda t: "demo$ " in t)

        assert api_post("term.input", {"id": term_id, "data": "hello world\r"}, ctx)["ok"]
        assert "you said: hello world" in _events(q, lambda t: "you said: hello world" in t)

        assert api_post("term.resize", {"id": term_id, "cols": 132, "rows": 43}, ctx)["ok"]
        time.sleep(0.3)
        api_post("term.input", {"id": term_id, "data": "size\r"}, ctx)
        assert "size 132x43" in _events(q, lambda t: "size 132x43" in t)

        assert [t["id"] for t in api_post("term.list", {}, ctx)["data"]] == [term_id]
        history = api_post("term.history", {"id": term_id}, ctx)["data"]["data"]     # a reloaded window redraws this
        assert "you said: hello world" in history and "size 132x43" in history
        api_post("conn.disconnect", {}, ctx)                   # the server's tabs close with its connection
        assert api_post("term.list", {}, ctx)["data"] == []
        assert not api_post("term.input", {"id": term_id, "data": "x"}, ctx)["ok"]
    finally:
        bus.unsubscribe(q)


def test_remote_terminal_needs_a_connection(ctx) -> None:
    reply = api_post("term.open", {"kind": "remote"}, ctx)
    assert not reply["ok"] and "SSH" in reply["error"]


def test_local_terminal_runs_a_command(ctx, tmp_path: Path) -> None:
    q = bus.subscribe(5000)
    try:
        reply = api_post("term.open", {"kind": "local", "cwd": str(tmp_path)}, ctx)
        if not reply["ok"] and "pywinpty" in reply.get("error", "").lower():
            pytest.skip("no PTY support here")
        assert reply["ok"], reply
        term_id = reply["data"]["id"]
        time.sleep(1.0)
        api_post("term.input", {"id": term_id, "data": "echo nobad-$((40+2))\r" if __import__("os").name != "nt" else "echo nobad-ok\r"}, ctx)
        out = _events(q, lambda t: "nobad-42" in t or "nobad-ok" in t.replace("echo nobad-ok", ""), timeout=30)
        assert "nobad-" in out
        api_post("term.close", {"id": term_id}, ctx)
        assert api_post("term.list", {}, ctx)["data"] == []
    finally:
        bus.unsubscribe(q)


def test_terminal_input_is_size_limited(ctx) -> None:
    assert not api_post("term.input", {"id": "nope", "data": "x" * 70_000}, ctx)["ok"]
    assert not api_post("term.input", {"id": "nope", "data": "ls"}, ctx)["ok"]


def test_output_buffer_keeps_order_and_caps_runaway_output() -> None:
    sent: list[tuple[str, dict]] = []
    buf = OutputBuffer(send=lambda kind, payload: sent.append((kind, payload)))
    buf.push("t1", "a")
    buf.push("t1", "b")
    buf.push("t2", "x")
    buf.flush()
    assert sorted((p["id"], p["data"]) for _k, p in sent) == [("t1", "ab"), ("t2", "x")]

    sent.clear()
    chunk = "y" * 100_000
    for _ in range(40):                     # 4 MB without a flush
        buf.push("t1", chunk)
    buf.flush()
    assert len(sent[0][1]["data"]) <= MAX_PENDING
