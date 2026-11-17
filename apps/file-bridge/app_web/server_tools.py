"""Server health and systemd services for the web UI, on ``core.health_monitor`` and ``core.services_manager``.

Server health
* One batch command (``/proc``, ``df``, ``ps``) per sample, parsed by ``ServerHealthCollector`` (which keeps the
  previous sample to turn counters into rates). Sampling runs only while a page asks for it: ``health.watch`` starts
  it and must be repeated at least every 30 s, so a closed or reloaded window stops it by itself. It also stops when
  the connection closes or changes. Samples go out as ``health.sample``; failures as ``health.error`` with a pause.
* Stopping a process sends SIGTERM (or SIGKILL when asked) and checks kill's exit status.

Services
* The inventory is one ``systemctl list-units`` + ``list-unit-files`` round trip. Unit names are always checked
  with ``validate_unit_name`` before they reach a command.
* Actions use ``sudo -n`` unless the login is root, so a server that wants a sudo password says so at once (the
  app never types a password into a server's prompt). Exit statuses are checked: a failed restart is reported as
  failed, with sudo's or systemctl's own reason.
* Logs are read without sudo first (users in systemd-journal or adm can read them) and with ``sudo -n`` only when
  the journal refuses."""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import asdict
from typing import Any

from app_web import bus, tasks
from app_web.files import FileError, run_sync
from core.async_runtime import AsyncRuntime
from core.health_monitor import TELEMETRY_SHELL_COMMAND, ServerHealthCollector, kill_remote_process, scan_remote_directory_sizes
from core.remote_command import command_error, command_ok, sudo_prefix, sudo_needs_password
from core.services_manager import (
    SERVICE_INVENTORY_COMMAND,
    SystemdServicesCollector,
    control_service,
    daemon_reload,
    fetch_unit_properties,
    install_unit_file,
    validate_unit_name,
)

LEASE = 30.0
INTERVALS = (1, 2, 5, 10)
ACTIONS = {"start", "stop", "restart", "reload", "enable", "disable"}
SCAN_KEY = "health.scan"
MAX_UNIT_FILE = 64 * 1024


class ToolError(FileError):
    pass


def _connection(session: Any) -> Any:
    current = session.current
    if current is None:
        raise ToolError("Connect to a server first.")
    caps = getattr(current, "capabilities", None)
    if caps is not None and not caps.can_exec_command:
        raise ToolError("This needs an SSH connection: it runs commands on the server.")
    return current


def _is_root(connection: Any) -> bool:
    return getattr(getattr(connection, "profile", None), "username", "") == "root"


# ---------------------------------------------------------------- server health
class HealthService:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.interval = 2
        self._lease_until = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._collector = ServerHealthCollector()
        self._for: Any = None
        self._gen = 0

    def watch(self, on: Any, interval: Any = None) -> dict[str, Any]:
        if interval is not None:
            try:
                value = int(interval)
            except (TypeError, ValueError):
                raise ToolError("Choose how often to refresh.") from None
            if value not in INTERVALS:
                raise ToolError("Choose how often to refresh.")
            self.interval = value
        if on is not True:
            self._lease_until = 0.0
            return {"watching": False, "interval": self.interval}
        connection = _connection(self.session)
        self._lease_until = time.monotonic() + LEASE
        with self._lock:
            start = not self._running or self._for is not connection      # a new connection gets a fresh loop
            if start:
                self._gen += 1
                self._running = True
                if self._for is not connection:
                    self._collector = ServerHealthCollector()
                    self._for = connection
                gen = self._gen
        if start:
            AsyncRuntime.instance().submit(self._loop(connection, gen))
        return {"watching": True, "interval": self.interval}

    async def _loop(self, connection: Any, gen: int) -> None:
        failures = 0
        try:
            while gen == self._gen and time.monotonic() < self._lease_until and self.session.current is connection:
                started = time.monotonic()
                try:
                    result = await asyncio.wait_for(connection.run_command(TELEMETRY_SHELL_COMMAND), 20)
                    stdout = str((result.data or {}).get("stdout", "")) if result.ok else ""
                    if "cpu " not in stdout:
                        raise ToolError("Server health needs a Linux server (it reads /proc).")
                    snapshot = self._collector.parse_batch(stdout)
                    bus.broadcast("health.sample", sample_payload(snapshot))
                    failures = 0
                except Exception as exc:          # reported, then retried after a pause
                    failures += 1
                    bus.broadcast("health.error", {"message": bus.scrub(str(exc)) or exc.__class__.__name__})
                    await asyncio.sleep(min(30, 2 ** failures))
                    continue
                await asyncio.sleep(max(0.2, self.interval - (time.monotonic() - started)))
        finally:
            with self._lock:
                if gen == self._gen:
                    self._running = False

    def kill(self, pid: Any, force: Any) -> str:
        connection = _connection(self.session)
        try:
            number = int(pid)
        except (TypeError, ValueError):
            raise ToolError("Unknown process.") from None
        if number <= 1:
            raise ToolError("That process can't be stopped from here.")
        result = run_sync(kill_remote_process(connection, number, force=force is True))
        if not result.ok:
            raise ToolError(result.message)
        bus.log(f"Sent {'SIGKILL' if force is True else 'SIGTERM'} to process {number}.", "warn", "health")
        return result.message

    def start_scan(self) -> bool:
        connection = _connection(self.session)

        async def work() -> None:
            found = await scan_remote_directory_sizes(connection)
            bus.broadcast("health.dirs", {"dirs": [asdict(d) for d in found]})

        return tasks.run_task(SCAN_KEY, work)


def sample_payload(s: Any) -> dict[str, Any]:
    data = asdict(s)
    data["processes"] = data["processes"][:20]
    return data


# ---------------------------------------------------------------- services
def unit_payload(u: Any) -> dict[str, Any]:
    return {"name": u.name, "description": u.description, "load": u.load_state, "active": u.active_state, "sub": u.sub_state,
            "boot": u.unit_file_state, "category": u.category, "ports": u.ports, "failed": u.is_failed,
            "running": u.is_running, "enabled": u.is_boot_enabled}


class ServicesService:
    def __init__(self, session: Any) -> None:
        self.session = session

    def _unit(self, name: Any) -> str:
        if not isinstance(name, str):
            raise ToolError("Unknown service.")
        try:
            return validate_unit_name(name)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    def inventory(self) -> dict[str, Any]:
        connection = _connection(self.session)
        result = run_sync(connection.run_command(SERVICE_INVENTORY_COMMAND), timeout=40)
        stdout = str((result.data or {}).get("stdout", "")) if result.ok else ""
        if not command_ok(result) and not stdout.strip():
            if "not found" in str((result.data or {}).get("stderr", "")):
                raise ToolError("This server doesn't use systemd, so there are no services to list.")
            raise ToolError(command_error(result, "Couldn't list the services"))
        snap = SystemdServicesCollector.parse_inventory(stdout, now=time.time())
        return {"total": snap.total_count, "running": snap.running_count, "stopped": snap.stopped_count,
                "failed": snap.failed_count, "enabled": snap.boot_enabled_count,
                "services": [unit_payload(u) for u in snap.services], "root": _is_root(connection)}

    def details(self, name: Any, lines: Any = 80, errors_only: Any = False) -> dict[str, Any]:
        unit = self._unit(name)
        connection = _connection(self.session)
        try:
            count = max(10, min(1000, int(lines)))
        except (TypeError, ValueError):
            count = 80
        props = run_sync(fetch_unit_properties(connection, unit), timeout=30)
        logs, note = run_sync(self._logs(connection, unit, count, errors_only is True), timeout=40)
        return {"name": unit, "props": {k: props.get(k, "") for k in ("Description", "LoadState", "ActiveState", "SubState",
                                                                      "UnitFileState", "MainPID", "MemoryCurrent", "CPUUsageNSec",
                                                                      "TasksCurrent", "Restart", "ExecStart")},
                "logs": [asdict(e) for e in logs], "logs_note": note}

    async def _logs(self, connection: Any, unit: str, count: int, errors_only: bool) -> tuple[tuple, str | None]:
        flag = " -p err" if errors_only else ""
        plain = f"journalctl -u {unit} -n {count} --no-pager{flag}"
        result = await connection.run_command(plain)
        out = str((result.data or {}).get("stdout", "")) if result.ok else ""
        err = str((result.data or {}).get("stderr", "")) if result.ok else ""
        refused = "insufficient permissions" in (out + err).lower() or "not seeing messages" in (out + err).lower()
        if command_ok(result) and not refused:
            return SystemdServicesCollector.parse_journal(out), None
        if _is_root(connection):
            return (), command_error(result, "Couldn't read the journal")
        retry = await connection.run_command(f"{sudo_prefix(True)}{plain}")
        if command_ok(retry):
            return SystemdServicesCollector.parse_journal(str((retry.data or {}).get("stdout", ""))), None
        if sudo_needs_password(retry):
            return (SystemdServicesCollector.parse_journal(out) if command_ok(result) else ()), (
                "Only some log lines are visible to this user. Add it to the systemd-journal group, or allow passwordless "
                "sudo for journalctl, to see all of them.")
        return (), command_error(retry, "Couldn't read the journal")

    def action(self, name: Any, action: Any) -> str:
        unit = self._unit(name)
        if action not in ACTIONS:
            raise ToolError("Unknown action.")
        connection = _connection(self.session)
        result = run_sync(control_service(connection, unit, action, sudo=not _is_root(connection)), timeout=90)
        if not result.ok:
            bus.log(result.message, "error", "services")
            raise ToolError(result.message)
        bus.log(f"{action.capitalize()}: {unit}", "ok", "services")
        return result.message

    def reload(self) -> str:
        connection = _connection(self.session)
        result = run_sync(daemon_reload(connection, sudo=not _is_root(connection)), timeout=60)
        if not result.ok:
            raise ToolError(result.message)
        bus.log("systemd reloaded its unit files.", "ok", "services")
        return result.message

    def install(self, name: Any, content: Any, start: Any) -> str:
        unit = self._unit(name)
        if not isinstance(content, str) or not content.strip():
            raise ToolError("Write the unit file first.")
        if len(content) > MAX_UNIT_FILE or "\0" in content:
            raise ToolError("The unit file is too large.")
        if "[Service]" not in content:
            raise ToolError("A service unit needs a [Service] section.")
        connection = _connection(self.session)
        result = run_sync(install_unit_file(connection, unit, content, enable_and_start=start is True, sudo=not _is_root(connection)),
                          timeout=90)
        if not result.ok:
            raise ToolError(result.message)
        bus.log(f"Installed {unit}.", "ok", "services")
        return result.message
