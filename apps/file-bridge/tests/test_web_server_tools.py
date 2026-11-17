"""Server health and services in the web UI. The server is a recording fake that returns real Linux/systemd output
(the commands themselves are what matters: unit names checked, sudo -n, exit statuses read)."""
from __future__ import annotations

import json
import queue
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app_web import bus, server_tools
from app_web.api import api_post
from app_web.context import AppContext
from app_web.handlers import register_all
from core.remote_command import command_error, command_ok, sudo_needs_password
from core.result import OperationResult
from test_health_monitor import MOCK_BATCH_OUTPUT_1, MOCK_BATCH_OUTPUT_2
from test_services_manager import MOCK_JOURNAL_OUTPUT, MOCK_LIST_UNITS_OUTPUT, MOCK_PROPERTIES_OUTPUT

register_all()


def _done(stdout: str = "", stderr: str = "", status: int = 0) -> OperationResult:
    return OperationResult.success("Command completed.", data={"stdout": stdout, "stderr": stderr, "exit_status": status})


class FakeServer:
    """Answers by command; ``rules`` are (prefix, result) pairs checked in order."""

    def __init__(self, username: str = "deploy") -> None:
        self.profile = SimpleNamespace(id="p1", name="web-1", host="web-1.example.com", username=username)
        self.capabilities = SimpleNamespace(can_exec_command=True)
        self.commands: list[str] = []
        self.rules: list[tuple[str, OperationResult]] = []
        self.batches = [MOCK_BATCH_OUTPUT_1, MOCK_BATCH_OUTPUT_2]

    async def run_command(self, command: str, *, cwd: str | None = None) -> OperationResult:
        self.commands.append(command)
        if command.startswith("cat /proc/stat"):
            return _done(self.batches.pop(0) if len(self.batches) > 1 else self.batches[0])
        for prefix, result in self.rules:
            if command.startswith(prefix):
                return result
        return _done()


@pytest.fixture
def ctx(tmp_path: Path):
    context = AppContext.create(tmp_path / "app.sqlite3")
    yield context
    context.health.watch(False)
    context.session.current = None


@pytest.fixture
def server(ctx: AppContext) -> FakeServer:
    fake = FakeServer()
    ctx.session.current = fake
    return fake


def _collect(kind: str, count: int, timeout: float = 15) -> list[dict]:
    q = bus.subscribe(500)
    got: list[dict] = []
    try:
        deadline = time.monotonic() + timeout
        while len(got) < count and time.monotonic() < deadline:
            try:
                msg = json.loads(q.get(timeout=0.3))
            except queue.Empty:
                continue
            if msg["type"] == kind:
                got.append(msg["payload"])
    finally:
        bus.unsubscribe(q)
    return got


# ---------------------------------------------------------------- reading command results
def test_a_command_only_worked_when_it_exited_with_zero() -> None:
    assert command_ok(_done("ok"))
    assert not command_ok(_done("", "Failed to restart nginx.service: Unit nginx.service not found.", 5))
    assert "not found" in command_error(_done("", "Failed to restart nginx.service: Unit nginx.service not found.", 5), "Couldn't restart")
    refused = _done("", "sudo: a password is required", 1)
    assert sudo_needs_password(refused) and "asks for a password" in command_error(refused, "Couldn't restart")


# ---------------------------------------------------------------- health
def test_health_samples_while_watched_and_stops_by_itself(ctx, server: FakeServer, monkeypatch: pytest.MonkeyPatch) -> None:
    q = bus.subscribe(500)
    try:
        assert api_post("health.watch", {"on": True, "interval": 1}, ctx)["ok"]
        samples = []
        deadline = time.monotonic() + 15
        while len(samples) < 2 and time.monotonic() < deadline:
            try:
                msg = json.loads(q.get(timeout=0.3))
            except queue.Empty:
                continue
            if msg["type"] == "health.sample":
                samples.append(msg["payload"])
    finally:
        bus.unsubscribe(q)
    assert len(samples) == 2
    assert samples[-1]["cpu_cores"] >= 1 and samples[-1]["mem_total_bytes"] > 0 and samples[-1]["processes"]

    ctx.health._lease_until = time.monotonic() - 1                   # the page stopped renewing
    time.sleep(1.5)
    before = len(server.commands)
    time.sleep(1.5)
    assert len(server.commands) == before


def test_health_explains_a_server_without_proc(ctx, server: FakeServer) -> None:
    server.batches = ["Darwin 23.1.0 arm64\n"]
    assert api_post("health.watch", {"on": True, "interval": 1}, ctx)["ok"]
    errors = _collect("health.error", 1)
    assert errors and "Linux" in errors[0]["message"]


def test_bad_refresh_intervals_are_refused(ctx, server: FakeServer) -> None:
    assert not api_post("health.watch", {"on": True, "interval": 0}, ctx)["ok"]


def test_stopping_a_process_reports_kills_own_error(ctx, server: FakeServer) -> None:
    server.rules = [("kill -15 4242", _done("", "kill: (4242) - Operation not permitted", 1))]
    reply = api_post("health.kill", {"pid": 4242}, ctx)
    assert not reply["ok"] and "Operation not permitted" in reply["error"]
    assert api_post("health.kill", {"pid": 777, "force": True}, ctx)["ok"]
    assert server.commands[-1] == "kill -9 777"
    assert not api_post("health.kill", {"pid": 1}, ctx)["ok"]
    assert not api_post("health.kill", {"pid": "1; reboot"}, ctx)["ok"]


# ---------------------------------------------------------------- services
def test_service_list(ctx, server: FakeServer) -> None:
    server.rules = [("systemctl list-units", _done(MOCK_LIST_UNITS_OUTPUT))]
    data = api_post("svc.list", {}, ctx)["data"]
    assert data["failed"] == 1 and data["total"] == 8 and data["root"] is False
    assert data["services"][0]["name"] == "celery-worker.service"                   # failed ones first


def test_no_systemd_is_explained(ctx, server: FakeServer) -> None:
    server.rules = [("systemctl list-units", _done("", "sh: 1: systemctl: not found", 127))]
    reply = api_post("svc.list", {}, ctx)
    assert not reply["ok"] and "systemd" in reply["error"]


def test_actions_use_non_interactive_sudo_and_report_failures(ctx, server: FakeServer) -> None:
    assert api_post("svc.action", {"name": "nginx", "action": "restart"}, ctx)["ok"]
    assert server.commands[-1] == "sudo -n systemctl restart nginx.service"

    server.rules = [("sudo -n systemctl stop", _done("", "sudo: a password is required", 1))]
    reply = api_post("svc.action", {"name": "nginx.service", "action": "stop"}, ctx)
    assert not reply["ok"] and "password" in reply["error"]                         # not "executed successfully"

    server.rules = [("sudo -n systemctl start", _done("", "Failed to start ghost.service: Unit ghost.service not found.", 5))]
    reply = api_post("svc.action", {"name": "ghost", "action": "start"}, ctx)
    assert not reply["ok"] and "not found" in reply["error"]


def test_root_logins_need_no_sudo(ctx) -> None:
    root = FakeServer(username="root")
    ctx.session.current = root
    assert api_post("svc.action", {"name": "nginx", "action": "reload"}, ctx)["ok"]
    assert root.commands[-1] == "systemctl reload nginx.service"


@pytest.mark.parametrize("name", ["nginx; reboot", "../x", "a$(id)", "", None])
def test_bad_unit_names_never_reach_the_server(ctx, server: FakeServer, name) -> None:  # type: ignore[no-untyped-def]
    for api_name, body in (("svc.action", {"name": name, "action": "restart"}), ("svc.details", {"name": name})):
        assert not api_post(api_name, body, ctx)["ok"]
    assert server.commands == []
    assert not api_post("svc.action", {"name": "nginx", "action": "mask"}, ctx)["ok"]
    assert server.commands == []


def test_logs_fall_back_to_sudo_only_when_the_journal_refuses(ctx, server: FakeServer) -> None:
    server.rules = [("systemctl show", _done(MOCK_PROPERTIES_OUTPUT)),
                    ("journalctl -u nginx.service", _done("Hint: You are currently not seeing messages from other users and the system.")),
                    ("sudo -n journalctl -u nginx.service", _done(MOCK_JOURNAL_OUTPUT))]
    data = api_post("svc.details", {"name": "nginx"}, ctx)["data"]
    assert data["props"]["MainPID"] == "14201" and len(data["logs"]) == 7 and data["logs_note"] is None
    assert server.commands[-1].startswith("sudo -n journalctl")

    server.rules = [("systemctl show", _done(MOCK_PROPERTIES_OUTPUT)), ("journalctl -u nginx.service", _done(MOCK_JOURNAL_OUTPUT))]
    server.commands.clear()
    assert len(api_post("svc.details", {"name": "nginx"}, ctx)["data"]["logs"]) == 7
    assert not any(c.startswith("sudo") for c in server.commands)


def test_installing_a_unit(ctx, server: FakeServer) -> None:
    assert not api_post("svc.install", {"name": "api", "content": "echo hi"}, ctx)["ok"]
    unit = "[Unit]\nDescription=API\n[Service]\nExecStart=/usr/bin/api\n"
    assert api_post("svc.install", {"name": "api", "content": unit, "start": True}, ctx)["ok"]
    assert "base64 -d | sudo -n tee /etc/systemd/system/api.service" in server.commands[-1]
    assert "sudo -n systemctl enable --now api.service" in server.commands[-1]


def test_tools_need_a_command_capable_connection(ctx) -> None:
    assert "Connect" in api_post("svc.list", {}, ctx)["error"]
    ctx.session.current = SimpleNamespace(profile=SimpleNamespace(id="f", username="u"), capabilities=SimpleNamespace(can_exec_command=False))
    assert "SSH" in api_post("health.watch", {"on": True}, ctx)["error"]
    assert server_tools.LEASE >= 20
