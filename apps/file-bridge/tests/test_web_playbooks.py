"""Playbooks in the web UI against a real AsyncSSH server (PTY exec channels): typed variable checks before
anything is rendered (no shell injection through a value), the sudo choice per run with the password answered only
to our own prompt and masked, "run without a password" turning sudo into sudo -n, exit codes, cancel, history, and
custom snippets."""
from __future__ import annotations

import asyncio
import json
import queue
import re
import time
from pathlib import Path

import pytest

asyncssh = pytest.importorskip("asyncssh")

from app_web import bus  # noqa: E402
from app_web.api import api_post  # noqa: E402
from app_web.context import AppContext  # noqa: E402
from app_web.handlers import register_all  # noqa: E402
from core.async_runtime import AsyncRuntime  # noqa: E402
from core.playbooks_manager import PREBUNDLED_RECIPES, check_variable_values  # noqa: E402

register_all()
USER, PASSWORD, SUDO_PW = "deploy", "s3cret-pass", "sudo-Pa55-word"
SEEN: list[str] = []


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USER and password == PASSWORD


async def _bash(process) -> None:  # type: ignore[no-untyped-def]
    """Plays bash -c '<script>' for what the tests need."""
    cmd = process.command or ""
    script = cmd[len("bash -c '"):-1].replace("'\"'\"'", "'") if cmd.startswith("bash -c '") else cmd
    SEEN.append(script)
    prompt = re.search(r"export SUDO_PROMPT=(\S+)", script)
    if prompt:
        process.stdout.write("Looks like a prompt: [sudo] password for deploy:\r\n")      # must NOT get the password
        process.stdout.write(prompt.group(1))
        line = (await process.stdin.readline()).strip()
        process.stdout.write(("uid=0(root) with " + line + "\r\n") if line == SUDO_PW else "Sorry, try again.\r\n")
        process.exit(0 if line == SUDO_PW else 1)
        return
    if "sleep-forever" in script:
        try:
            while True:
                process.stdout.write(".")
                await asyncio.sleep(0.1)
        except Exception:
            return
    code = 0
    for line in script.splitlines():
        line = line.strip()
        if line.startswith("echo "):
            process.stdout.write(line[5:].strip("\"'") + "\r\n")
        elif line.startswith("exit "):
            code = int(line[5:])
            break
    process.exit(code)


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
        srv = await asyncssh.create_server(_Server, "127.0.0.1", 0, server_host_keys=[key], process_factory=_bash,
                                           sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(tmp_path)))
        return srv, srv.sockets[0].getsockname()[1]

    srv, port = AsyncRuntime.instance().run(start())
    SEEN.clear()
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


def _run(ctx: AppContext, body: dict, *, cancel_after: float | None = None) -> tuple[dict, str]:
    q = bus.subscribe(5000)
    out: list[str] = []
    try:
        reply = api_post("pb.run", body, ctx)
        assert reply["ok"], reply
        if cancel_after:
            time.sleep(cancel_after)
            api_post("pb.cancel", {}, ctx)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                msg = json.loads(q.get(timeout=0.3))
            except queue.Empty:
                continue
            if msg["type"] == "pb.out":
                out.append(msg["payload"]["data"])
            if msg["type"] == "pb.done":
                time.sleep(0.2)
                while not q.empty():
                    m = json.loads(q.get_nowait())
                    if m["type"] == "pb.out":
                        out.append(m["payload"]["data"])
                return msg["payload"], "".join(out)
        raise AssertionError("no pb.done")
    finally:
        bus.unsubscribe(q)


def _snippet(ctx: AppContext, script: str, **extra) -> str:  # type: ignore[no-untyped-def]
    reply = api_post("pb.save", {"recipe": {"title": "Test", "script": script, **extra}}, ctx)
    assert reply["ok"], reply
    return reply["data"]["id"]


def test_every_bundled_playbook_accepts_its_own_defaults() -> None:
    for recipe in PREBUNDLED_RECIPES:
        check_variable_values(recipe.variables, {}, recipe.script_template)


@pytest.mark.parametrize("value", ["example.com; rm -rf ~", "$(reboot)", "`id`", "a && b", "x\ny", "a|b", "> /etc/passwd"])
def test_a_value_can_never_run_as_a_command(ctx, value: str) -> None:
    reply = api_post("pb.render", {"id": "certbot-ssl", "values": {"DOMAIN": value}}, ctx)
    assert not reply["ok"] and "can only contain" in reply["error"]


def test_typed_values_and_single_quoted_regexes() -> None:
    recipe = next(r for r in PREBUNDLED_RECIPES if r.id == "check-ports")
    ok = check_variable_values(recipe.variables, {"PROCESS_FILTER": "nginx|node"}, recipe.script_template)
    assert ok["PROCESS_FILTER"] == "nginx|node"                                  # only inside '...': a pipe is fine
    with pytest.raises(ValueError):
        check_variable_values(recipe.variables, {"PROCESS_FILTER": "x'; reboot; '"}, recipe.script_template)
    dry = next(r for r in PREBUNDLED_RECIPES if r.id == "certbot-ssl")
    with pytest.raises(ValueError):
        check_variable_values(dry.variables, {"DRY_RUN": "maybe"}, dry.script_template)


def test_a_run_streams_output_and_is_recorded(ssh_port, ctx) -> None:
    _connect(ctx, ssh_port)
    sid = _snippet(ctx, "echo Checking {{SITE}}\necho all good\nexit 0\n")
    done, out = _run(ctx, {"id": sid, "values": {"SITE": "shop.example.com"}})
    assert done["ok"] and done["status"] == "success" and "Checking shop.example.com" in out
    history = api_post("pb.history", {"id": sid}, ctx)["data"]
    assert history[0]["status"] == "success" and "all good" in history[0]["output"]

    failing = _snippet(ctx, "echo nope\nexit 3\n")
    done, _ = _run(ctx, {"id": failing})
    assert not done["ok"] and done["exit_code"] == 3 and done["status"] == "failed"


def test_sudo_needs_a_choice_and_the_password_only_answers_our_prompt(ssh_port, ctx) -> None:
    _connect(ctx, ssh_port)
    sid = _snippet(ctx, "sudo id\n")
    refused = api_post("pb.run", {"id": sid}, ctx)
    assert not refused["ok"] and "sudo" in refused["error"]

    done, out = _run(ctx, {"id": sid, "sudo": "password", "password": SUDO_PW})
    assert done["ok"], (done, out)
    assert SUDO_PW not in out and "********" in out                               # echoed back, but masked
    assert "Looks like a prompt" in out                                           # the look-alike got nothing
    history = json.dumps(api_post("pb.history", {"id": sid}, ctx)["data"])
    assert SUDO_PW not in history and SUDO_PW not in json.dumps(bus.recent_log())


def test_running_without_a_password_makes_sudo_non_interactive(ssh_port, ctx) -> None:
    _connect(ctx, ssh_port)
    sid = _snippet(ctx, "sudo systemctl reload nginx\necho reloaded\n")
    done, _ = _run(ctx, {"id": sid, "sudo": "none"})
    assert done["ok"]
    assert SEEN[-1].startswith('sudo() { command sudo -n "$@"; }\nexport -f sudo\n')


def test_destructive_playbooks_need_confirmation(ssh_port, ctx) -> None:
    _connect(ctx, ssh_port)
    reply = api_post("pb.run", {"id": "docker-prune", "sudo": "none"}, ctx)
    assert not reply["ok"] and "Confirm" in reply["error"]


def test_a_run_can_be_cancelled(ssh_port, ctx) -> None:
    _connect(ctx, ssh_port)
    sid = _snippet(ctx, "echo start\nsleep-forever\n")
    done, _ = _run(ctx, {"id": sid}, cancel_after=0.8)
    assert not done["ok"] and done["status"] in {"cancelled", "failed"}


def test_custom_snippets_find_their_variables_and_bundled_ones_stay_read_only(ctx) -> None:
    sid = _snippet(ctx, "echo {{TARGET}}\n{{#if VERBOSE}}echo more{{/if}}\n", description="mine")
    recipe = next(r for r in api_post("pb.list", {}, ctx)["data"]["recipes"] if r["id"] == sid)
    assert [v["key"] for v in recipe["variables"]] == ["TARGET", "VERBOSE"] and recipe["custom"] is True
    assert api_post("pb.favorite", {"id": sid}, ctx)["data"]["favorite"] is True
    assert not api_post("pb.save", {"recipe": {"id": "certbot-ssl", "title": "x", "script": "echo"}}, ctx)["ok"]
    assert not api_post("pb.delete", {"id": "certbot-ssl"}, ctx)["ok"]
    assert api_post("pb.delete", {"id": sid}, ctx)["ok"]


def test_playbooks_need_an_ssh_connection(ctx) -> None:
    reply = api_post("pb.run", {"id": "check-ports"}, ctx)
    assert not reply["ok"] and "Connect" in reply["error"]
