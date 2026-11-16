from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

from core.result import OperationResult

# Compound command gathering all service units and boot enable states in a single SSH round-trip
SERVICE_INVENTORY_COMMAND = (
    "systemctl list-units --type=service --all --no-pager --no-legend; "
    "echo '===BOOT==='; "
    "systemctl list-unit-files --type=service --no-pager --no-legend"
)

# Known service categories mapping regex
CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("web", ("nginx", "apache", "caddy", "httpd", "traefik", "lighttpd")),
    ("database", ("postgres", "mysql", "mariadb", "redis", "mongodb", "clickhouse", "sqlite", "memcached")),
    ("container", ("docker", "containerd", "podman", "k3s", "kubelet", "cri-o")),
    ("worker", ("celery", "gunicorn", "uvicorn", "fastapi", "flask", "django", "node", "pm2", "supervisor", "sidekiq", "rq")),
    ("security", ("ssh", "sshd", "fail2ban", "ufw", "iptables", "firewalld", "apparmor", "clamav")),
)


def validate_unit_name(unit_name: str) -> str:
    """
    Strictly validate and normalize a systemd unit name.
    Rejects path traversal, path separators, and shell metacharacters.
    Returns normalized unit name ending with '.service'.
    """
    clean = unit_name.strip()
    if not clean or "/" in clean or "\\" in clean or ".." in clean:
        raise ValueError(f"Invalid unit name '{unit_name}': cannot contain path separators or parent directory references.")

    # Only allow safe systemd unit characters: alphanumeric, dots, dashes, underscores, and @ for template units
    if not re.match(r"^[\w\.\-@]+(?:\.service)?$", clean):
        raise ValueError(f"Invalid unit name '{unit_name}': contains forbidden characters.")

    if not clean.endswith(".service"):
        clean = f"{clean}.service"

    return clean


def categorize_service(unit_name: str) -> str:
    """Classify service into an intuitive category tag based on its unit name."""
    name_lower = unit_name.lower()
    for cat, keywords in CATEGORY_PATTERNS:
        if any(kw in name_lower for kw in keywords):
            return cat
    return "system"


def detect_service_ports(unit_name: str) -> str:
    """Infer common protocol listening ports for prominent services."""
    name_lower = unit_name.lower()
    if "nginx" in name_lower or "caddy" in name_lower or "httpd" in name_lower or "apache" in name_lower:
        return ":80, :443"
    if "postgres" in name_lower:
        return ":5432"
    if "mysql" in name_lower or "mariadb" in name_lower:
        return ":3306"
    if "redis" in name_lower:
        return ":6379"
    if "ssh" in name_lower:
        return ":22"
    if "docker" in name_lower:
        return "/var/run/docker.sock"
    if "mongodb" in name_lower or "mongod" in name_lower:
        return ":27017"
    return ""


@dataclass(frozen=True, slots=True)
class ServiceUnitInfo:
    """Information and telemetry for a single systemd service unit."""
    name: str
    description: str
    load_state: str        # loaded, not-found, bad-setting, error, masked
    active_state: str      # active, inactive, failed, activating, deactivating
    sub_state: str         # running, dead, exited, failed, auto-restart
    unit_file_state: str   # enabled, disabled, static, masked, indirect, unknown
    pid: int
    memory_bytes: int
    cpu_nsec: int
    tasks_current: int
    tasks_max: int
    restart_policy: str
    exec_start: str
    category: str
    ports: str
    is_failed: bool
    is_running: bool
    is_boot_enabled: bool


@dataclass(frozen=True, slots=True)
class ServiceJournalEntry:
    """A single log line entry from journalctl for a unit."""
    timestamp: str
    sender: str
    message: str
    priority: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class ServiceInventorySnapshot:
    """Comprehensive snapshot of all discovered services on the server."""
    timestamp: float
    total_count: int
    running_count: int
    stopped_count: int
    failed_count: int
    boot_enabled_count: int
    services: tuple[ServiceUnitInfo, ...]


class SystemdServicesCollector:
    """Agentless parser for systemd service inventories, properties, and journalctl logs."""

    @staticmethod
    def parse_inventory(raw_stdout: str, now: float = 0.0) -> ServiceInventorySnapshot:
        """Parse compound output of list-units and list-unit-files."""
        if not raw_stdout:
            return ServiceInventorySnapshot(now, 0, 0, 0, 0, 0, ())

        parts = raw_stdout.split("===BOOT===")
        units_part = parts[0] if len(parts) > 0 else ""
        boot_part = parts[1] if len(parts) > 1 else ""

        # 1. Parse boot enablement mapping: unit_file -> state (enabled / disabled / static)
        boot_states: dict[str, str] = {}
        for line in boot_part.splitlines():
            line = line.strip()
            if not line or line.startswith("UNIT FILE"):
                continue
            cols = line.split()
            if len(cols) >= 2:
                u_name = cols[0]
                state = cols[1].lower()
                boot_states[u_name] = state

        # 2. Parse units list
        services_list: list[ServiceUnitInfo] = []
        for line in units_part.splitlines():
            line = line.strip()
            if not line:
                continue

            # Strip leading marker chars like ● or *
            cleaned = re.sub(r"^[●\*·\s]+", "", line)
            cols = cleaned.split(None, 4)
            if len(cols) < 4:
                continue

            name = cols[0]
            if not name.endswith(".service"):
                continue

            load_state = cols[1].lower()
            active_state = cols[2].lower()
            sub_state = cols[3].lower()
            description = cols[4] if len(cols) >= 5 else ""

            unit_file_state = boot_states.get(name, "unknown")
            is_running = active_state == "active"
            is_failed = active_state == "failed" or sub_state == "failed"
            is_boot_enabled = unit_file_state == "enabled"

            category = categorize_service(name)
            ports = detect_service_ports(name)

            services_list.append(
                ServiceUnitInfo(
                    name=name,
                    description=description,
                    load_state=load_state,
                    active_state=active_state,
                    sub_state=sub_state,
                    unit_file_state=unit_file_state,
                    pid=0,
                    memory_bytes=0,
                    cpu_nsec=0,
                    tasks_current=0,
                    tasks_max=0,
                    restart_policy="unknown",
                    exec_start="",
                    category=category,
                    ports=ports,
                    is_failed=is_failed,
                    is_running=is_running,
                    is_boot_enabled=is_boot_enabled,
                )
            )

        # Sort with failed first, then running, then stopped; alphabetically within
        def sort_priority(s: ServiceUnitInfo) -> tuple[int, str]:
            if s.is_failed:
                return (0, s.name)
            if s.is_running:
                return (1, s.name)
            return (2, s.name)

        services_list.sort(key=sort_priority)

        total_count = len(services_list)
        running_count = sum(1 for s in services_list if s.is_running)
        failed_count = sum(1 for s in services_list if s.is_failed)
        stopped_count = sum(1 for s in services_list if not s.is_running and not s.is_failed)
        boot_enabled_count = sum(1 for s in services_list if s.is_boot_enabled)

        return ServiceInventorySnapshot(
            timestamp=now,
            total_count=total_count,
            running_count=running_count,
            stopped_count=stopped_count,
            failed_count=failed_count,
            boot_enabled_count=boot_enabled_count,
            services=tuple(services_list),
        )

    @staticmethod
    def parse_properties(raw_stdout: str) -> dict[str, str]:
        """Parse key=value properties from `systemctl show <unit>`."""
        props: dict[str, str] = {}
        for line in raw_stdout.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            val = v.strip()
            # Guard against UINT64_MAX for MemoryCurrent (accounting disabled)
            if k == "MemoryCurrent" and val.isdigit() and int(val) >= 18446744073709551615:
                val = "0"
            props[k.strip()] = val
        return props

    @staticmethod
    def parse_journal(raw_stdout: str) -> tuple[ServiceJournalEntry, ...]:
        """Parse journalctl output into structured log line objects."""
        entries: list[ServiceJournalEntry] = []
        if not raw_stdout:
            return ()

        # Standard journal format: Oct 27 09:40:12 hostname process[pid]: message
        pattern = re.compile(r"^([A-Z][a-z]{2}\s+\d+\s+[\d:]+)\s+([\w\.\-]+)\s+([\w\.\-]+(?:\[\d+\])?):\s+(.*)$")

        for line in raw_stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-- Journal begins") or line.startswith("-- Logs begin"):
                continue

            match = pattern.match(line)
            if match:
                time_str = match.group(1)
                sender = match.group(3)
                msg = match.group(4)
            else:
                time_str = ""
                sender = ""
                msg = line

            msg_lower = msg.lower()
            is_error = any(kw in msg_lower for kw in ("fail", "error", "exception", "fatal", "critical", "denied", "refused", "exit-code"))

            entries.append(
                ServiceJournalEntry(
                    timestamp=time_str,
                    sender=sender,
                    message=msg,
                    priority="err" if is_error else "info",
                    is_error=is_error,
                )
            )

        return tuple(entries)


# Async execution operations over SSH
async def control_service(connection: Any, unit_name: str, action: str, sudo: bool = True) -> OperationResult:
    """
    Execute systemctl action on a service (start, stop, restart, reload, enable, disable).
    Automatically wraps with sudo when connected as a non-root user.
    """
    if connection is None:
        return OperationResult.failure("Cannot execute service action: No active SSH connection.")

    valid_actions = {"start", "stop", "restart", "reload", "enable", "disable"}
    if action not in valid_actions:
        return OperationResult.failure(f"Invalid systemctl action '{action}'. Expected one of {valid_actions}.")

    try:
        safe_name = validate_unit_name(unit_name)
    except ValueError as exc:
        return OperationResult.failure(str(exc))

    prefix = "sudo " if sudo else ""
    cmd = f"{prefix}systemctl {action} {safe_name}"

    try:
        res = await connection.run_command(cmd)
        if res.ok:
            return OperationResult.success(f"systemctl {action} {safe_name} executed successfully.")
        return OperationResult.failure(f"Failed to {action} {safe_name}: {res.message}")
    except Exception as exc:
        return OperationResult.failure(f"Error executing {action} for {safe_name}: {exc}")


async def daemon_reload(connection: Any, sudo: bool = True) -> OperationResult:
    """Execute `systemctl daemon-reload` to update systemd with changed unit definitions."""
    if connection is None:
        return OperationResult.failure("Cannot execute daemon-reload: No active SSH connection.")

    prefix = "sudo " if sudo else ""
    cmd = f"{prefix}systemctl daemon-reload"

    try:
        res = await connection.run_command(cmd)
        if res.ok:
            return OperationResult.success("systemctl daemon-reload executed successfully.")
        return OperationResult.failure(f"Failed to reload daemon: {res.message}")
    except Exception as exc:
        return OperationResult.failure(f"Error reloading systemd daemon: {exc}")


async def fetch_unit_properties(connection: Any, unit_name: str) -> dict[str, str]:
    """Retrieve deep CGroup, memory, PID, and ExecStart properties for a unit."""
    if connection is None:
        return {}

    try:
        safe_name = validate_unit_name(unit_name)
    except ValueError:
        return {}

    cmd = (
        f"systemctl show {safe_name} "
        "--property=Id,Description,LoadState,ActiveState,SubState,UnitFileState,MainPID,MemoryCurrent,CPUUsageNSec,TasksCurrent,TasksMax,Restart,ExecStart"
    )

    try:
        res = await connection.run_command(cmd)
        if not res.ok or not res.data:
            return {}
        stdout = res.data.get("stdout", "")
        return SystemdServicesCollector.parse_properties(stdout)
    except Exception:
        return {}


async def fetch_unit_logs(
    connection: Any,
    unit_name: str,
    lines: int = 50,
    errors_only: bool = False,
    sudo: bool = True,
) -> tuple[ServiceJournalEntry, ...]:
    """Fetch recent journalctl logs for a unit."""
    if connection is None:
        return ()

    try:
        safe_name = validate_unit_name(unit_name)
    except ValueError:
        return ()

    err_flag = " -p err" if errors_only else ""
    prefix = "sudo " if sudo else ""
    cmd = f"{prefix}journalctl -u {safe_name} -n {int(lines)} --no-pager{err_flag}"

    try:
        res = await connection.run_command(cmd)
        if not res.ok or not res.data:
            return ()
        stdout = res.data.get("stdout", "")
        return SystemdServicesCollector.parse_journal(stdout)
    except Exception:
        return ()


async def install_unit_file(
    connection: Any,
    unit_name: str,
    content: str,
    enable_and_start: bool = True,
    sudo: bool = True,
) -> OperationResult:
    """
    Safely write a systemd unit file directly to /etc/systemd/system/ using base64 decoding,
    reload the systemd daemon, and optionally enable and start it.
    """
    if connection is None:
        return OperationResult.failure("Cannot install unit: No active SSH connection.")

    try:
        safe_name = validate_unit_name(unit_name)
    except ValueError as exc:
        return OperationResult.failure(str(exc))

    target_path = f"/etc/systemd/system/{safe_name}"

    # Use base64 encoding to prevent POSIX echo backslash expansion corruption and shell quoting errors
    b64_content = base64.b64encode(content.encode("utf-8")).decode("ascii")

    prefix = "sudo " if sudo else ""
    cmd = (
        f"echo {b64_content} | base64 -d | {prefix}tee {target_path} >/dev/null && "
        f"{prefix}systemctl daemon-reload"
    )
    if enable_and_start:
        cmd += f" && {prefix}systemctl enable --now {safe_name}"

    try:
        res = await connection.run_command(cmd)
        if res.ok:
            return OperationResult.success(f"Unit file installed at {target_path} and daemon reloaded.")
        return OperationResult.failure(f"Failed to install unit file: {res.message}")
    except Exception as exc:
        return OperationResult.failure(f"Error installing unit file: {exc}")
