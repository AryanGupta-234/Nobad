from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import inspect
import logging
import re
import shlex
import time
from typing import Any
import uuid

from core.remote_command import sudo_prefix
from core.result import OperationResult, result_from_exception

logger = logging.getLogger("remote_file_manager.log_streamer")


class LogSourceType(StrEnum):
    FILE = "file"           # Standard remote file tailed via `tail -F`
    JOURNAL = "journal"     # systemd journal unit via `journalctl -u`


class LogStreamStatus(StrEnum):
    STREAMING = "streaming"
    PAUSED = "paused"
    STOPPED = "stopped"
    CONNECTING = "connecting"
    ERROR = "error"


@dataclass(slots=True)
class LogEntry:
    timestamp: str
    level: str  # "error", "warn", "info", "debug", "success", "default"
    source: str
    text: str
    raw: str
    line_number: int
    status_code: int | None = None
    client_ip: str | None = None
    method: str | None = None
    path: str | None = None
    duration: str | None = None
    size: str | None = None
    unit: str | None = None
    pid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "source": self.source,
            "text": self.text,
            "raw": self.raw,
            "line_number": self.line_number,
            "status_code": self.status_code,
            "client_ip": self.client_ip,
            "method": self.method,
            "path": self.path,
            "duration": self.duration,
            "size": self.size,
            "unit": self.unit,
            "pid": self.pid,
        }


@dataclass(slots=True)
class LogStreamConfig:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "Log Stream"
    source_type: LogSourceType = LogSourceType.FILE
    target_path: str = "/var/log/syslog"
    unit_name: str = ""
    bootstrap_lines: int = 150
    follow_rotations: bool = True
    use_sudo: bool = False
    category: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_type": str(self.source_type),
            "target_path": self.target_path,
            "unit_name": self.unit_name,
            "bootstrap_lines": self.bootstrap_lines,
            "follow_rotations": self.follow_rotations,
            "use_sudo": self.use_sudo,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LogStreamConfig":
        st = LogSourceType(data.get("source_type", "file"))
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            name=data.get("name", "Log Stream"),
            source_type=st,
            target_path=data.get("target_path", "/var/log/syslog"),
            unit_name=data.get("unit_name", ""),
            bootstrap_lines=int(data.get("bootstrap_lines", 150)),
            follow_rotations=bool(data.get("follow_rotations", True)),
            use_sudo=bool(data.get("use_sudo", False)),
            category=data.get("category", "system"),
        )


@dataclass(slots=True)
class LogStreamSession:
    config: LogStreamConfig
    status: LogStreamStatus = LogStreamStatus.CONNECTING
    process: Any = None
    started_at: float = 0.0
    lines_received: int = 0
    bytes_received: int = 0
    velocity: float = 0.0
    error_message: str | None = None
    ring_buffer: deque[LogEntry] = field(default_factory=lambda: deque(maxlen=10000))
    _last_calc_time: float = 0.0
    _last_calc_lines: int = 0
    _paused: bool = False


DEFAULT_LOG_PRESETS: list[dict[str, Any]] = [
    {
        "id": "preset-nginx-access",
        "name": "Nginx Access",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/nginx/access.log",
        "unit_name": "nginx.service",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": False,
        "category": "web",
    },
    {
        "id": "preset-nginx-error",
        "name": "Nginx Error",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/nginx/error.log",
        "unit_name": "nginx.service",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": False,
        "category": "web",
    },
    {
        "id": "preset-syslog",
        "name": "System Syslog",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/syslog",
        "unit_name": "",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": False,
        "category": "system",
    },
    {
        "id": "preset-auth",
        "name": "Auth / SSH Security",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/auth.log",
        "unit_name": "ssh.service",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": True,
        "category": "security",
    },
    {
        "id": "preset-postgres",
        "name": "PostgreSQL",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/postgresql/postgresql-16-main.log",
        "unit_name": "postgresql.service",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": False,
        "category": "database",
    },
    {
        "id": "preset-mysql",
        "name": "MySQL / MariaDB",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/mysql/error.log",
        "unit_name": "mysql.service",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": False,
        "category": "database",
    },
    {
        "id": "preset-apache-access",
        "name": "Apache Access",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/apache2/access.log",
        "unit_name": "apache2.service",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": False,
        "category": "web",
    },
    {
        "id": "preset-apache-error",
        "name": "Apache Error",
        "source_type": LogSourceType.FILE,
        "target_path": "/var/log/apache2/error.log",
        "unit_name": "apache2.service",
        "bootstrap_lines": 150,
        "follow_rotations": True,
        "use_sudo": False,
        "category": "web",
    },
]


# Regular expressions for log level detection and access log parsing
ACCESS_LOG_REGEX = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+"(?P<method>[A-Z]+)\s+(?P<path>[^\s"]+)[^"]*"\s+(?P<status>\d{3})\s+(?P<size>\S+)(?:\s+(?P<dur>\S+))?'
)

LEVEL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("error", re.compile(r"\b(error|fatal|crit|critical|alert|emerg|exception|failed|panic)\b", re.IGNORECASE)),
    ("warn", re.compile(r"\b(warn|warning)\b", re.IGNORECASE)),
    ("debug", re.compile(r"\b(debug|trace)\b", re.IGNORECASE)),
    ("info", re.compile(r"\b(info|notice)\b", re.IGNORECASE)),
)


def detect_log_level(raw: str, status_code: int | None = None) -> str:
    """Classify log line into semantic color level."""
    if status_code is not None:
        if status_code >= 500:
            return "error"
        if status_code >= 400:
            return "warn"
        if 200 <= status_code < 300:
            return "success"
        if 300 <= status_code < 400:
            return "info"

    for level, pattern in LEVEL_PATTERNS:
        if pattern.search(raw):
            return level
    return "default"


def parse_log_line(raw: str, source: str, line_no: int) -> LogEntry:
    """
    Parse a single raw log string into a structured LogEntry.
    Recognizes Nginx/Apache Combined Access format, error logs, and syslog formats.
    """
    clean = raw.rstrip("\r\n")

    # 1. Attempt access log regex parse
    m = ACCESS_LOG_REGEX.match(clean)
    if m:
        gd = m.groupdict()
        try:
            status_code = int(gd["status"])
        except (ValueError, TypeError):
            status_code = None

        size_raw = gd.get("size", "-")
        size_str = size_raw if size_raw != "-" else "0B"
        if size_str.isdigit():
            val = int(size_str)
            size_str = f"{val / 1024:.1f}KB" if val >= 1024 else f"{val}B"

        dur = gd.get("dur")
        dur_str = f"{dur}ms" if dur and not dur.endswith("ms") else dur

        lvl = detect_log_level(clean, status_code)
        return LogEntry(
            timestamp=gd.get("time", ""),
            level=lvl,
            source=source,
            text=clean,
            raw=clean,
            line_number=line_no,
            status_code=status_code,
            client_ip=gd.get("ip"),
            method=gd.get("method"),
            path=gd.get("path"),
            duration=dur_str,
            size=size_str,
        )

    # 2. Generic syslog / daemon format: "Oct 29 15:40:12 host daemon[123]: message"
    timestamp = ""
    unit = None
    pid = None
    text = clean

    # Match standard syslog timestamp prefix (e.g. "Oct 29 15:40:12" or "2026-10-29T15:40:12")
    syslog_m = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}|\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+(.*)$", clean)
    if syslog_m:
        timestamp = syslog_m.group(1)
        rest = syslog_m.group(2)
        # Check host and unit: "hostname unit[pid]: text"
        unit_m = re.match(r"^(?:\S+\s+)?([a-zA-Z0-9_\-\.]+)(?:\[(\d+)\])?:\s*(.*)$", rest)
        if unit_m:
            unit = unit_m.group(1)
            pid = unit_m.group(2)
            text = unit_m.group(3)
        else:
            text = rest
    else:
        # Check nginx error log timestamp: "2026/10/29 15:42:01 [error] 14205#14205: text"
        err_m = re.match(r"^(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[([a-z]+)\]\s+(?:(\d+#\d+):\s*)?(.*)$", clean)
        if err_m:
            timestamp = err_m.group(1)
            lvl = err_m.group(2).lower()
            pid = err_m.group(3)
            text = err_m.group(4)
            return LogEntry(
                timestamp=timestamp,
                level="error" if lvl in ("error", "crit", "alert", "emerg") else "warn" if lvl == "warn" else "info",
                source=source,
                text=text,
                raw=clean,
                line_number=line_no,
                pid=pid,
            )

    lvl = detect_log_level(clean)
    return LogEntry(
        timestamp=timestamp,
        level=lvl,
        source=source,
        text=text,
        raw=clean,
        line_number=line_no,
        unit=unit,
        pid=pid,
    )


async def _exit_reason(process: Any) -> str | None:
    """Why a tail/journalctl process ended by itself (no such file, permission denied, sudo wants a password)."""
    try:
        status = await asyncio.wait_for(process.wait(), timeout=1.0) if hasattr(process, "wait") else None
    except Exception:
        return None
    code = getattr(status, "exit_status", None) if status is not None else getattr(process, "exit_status", None)
    if not code:
        return None
    err = getattr(status, "stderr", None) or ""          # asyncssh's wait() collects what was left on stderr
    stderr = getattr(process, "stderr", None)
    if not err and stderr is not None and hasattr(stderr, "read"):
        try:
            err = await asyncio.wait_for(stderr.read(), timeout=1.0)
        except Exception:
            err = ""
    text = " ".join(str(err).split())[:300]
    if "a password is required" in text or "a terminal is required" in text:
        return "sudo on this server asks for a password. Allow passwordless sudo for tail/journalctl, or read the log as a user who may."
    return text or f"The log command ended with status {code}."


class LogStreamManager:
    """
    Manages active remote log streaming processes over AsyncSSH sessions.
    Maintains memory-bounded ring buffers, tracks velocity stats, and delivers
    batched log events asynchronously.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, LogStreamSession] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def get_session(self, stream_id: str) -> LogStreamSession | None:
        return self._sessions.get(stream_id)

    def get_active_sessions(self) -> list[LogStreamSession]:
        return list(self._sessions.values())

    def get_stats(self) -> dict[str, Any]:
        """Return aggregated KPIs across all managed streams."""
        total_streams = len(self._sessions)
        active_streams = sum(1 for s in self._sessions.values() if s.status == LogStreamStatus.STREAMING)
        total_lines = sum(s.lines_received for s in self._sessions.values())
        total_velocity = sum(s.velocity for s in self._sessions.values() if s.status == LogStreamStatus.STREAMING)
        total_buffered = sum(len(s.ring_buffer) for s in self._sessions.values())
        return {
            "total_streams": total_streams,
            "active_streams": active_streams,
            "total_lines": total_lines,
            "total_velocity": round(total_velocity, 1),
            "total_buffered": total_buffered,
        }

    async def start_stream(
        self,
        config: LogStreamConfig,
        connection: Any,
        on_entry: Callable[[LogEntry], None],
    ) -> OperationResult:
        """
        Start a new log tailing stream over the given SSH connection.
        Spawns `tail -F` or `journalctl` process and starts the async reader loop.
        """
        if connection is None:
            return OperationResult.failure("Cannot start log stream: No active SSH connection.")

        if callable(getattr(connection, "create_process", None)):
            ssh_conn = connection
        elif hasattr(connection, "_connection") and getattr(connection, "_connection", None) is not None:
            ssh_conn = getattr(connection, "_connection")
        else:
            ssh_conn = connection

        session = LogStreamSession(config=config, status=LogStreamStatus.CONNECTING, started_at=time.time())
        session._last_calc_time = time.time()
        self._sessions[config.id] = session

        # Build remote command string
        if config.source_type == LogSourceType.JOURNAL:
            cmd = f"{sudo_prefix(config.use_sudo)}journalctl -u {shlex.quote(config.unit_name)} -f -n {int(config.bootstrap_lines)} -o short-iso"
        else:
            follow_flag = "-F" if config.follow_rotations else "-f"
            cmd = f"{sudo_prefix(config.use_sudo)}tail {follow_flag} -n {int(config.bootstrap_lines)} {shlex.quote(config.target_path)}"

        try:
            # Create process via asyncssh
            call_res = ssh_conn.create_process(cmd)
            if inspect.isawaitable(call_res):
                process = await call_res
            else:
                process = call_res
            session.process = process
            session.status = LogStreamStatus.STREAMING
            logger.info("Started log stream %s: %s", config.name, cmd)

            # Spawn reader task
            task = asyncio.create_task(self._stream_reader_loop(config.id, process, on_entry))
            self._tasks[config.id] = task

            return OperationResult.success(
                f"Log stream '{config.name}' started.",
                data={"stream_id": config.id, "command": cmd},
            )
        except Exception as exc:
            session.status = LogStreamStatus.ERROR
            session.error_message = str(exc)
            logger.error("Failed to start log stream %s: %s", config.name, exc)
            return result_from_exception(f"Failed to start log stream '{config.name}'.", exc)

    async def _stream_reader_loop(
        self,
        stream_id: str,
        process: Any,
        on_entry: Callable[[LogEntry], None],
    ) -> None:
        """Continuously read lines from the process stdout and dispatch."""
        session = self._sessions.get(stream_id)
        if not session:
            return

        line_counter = 0
        try:
            while True:
                if hasattr(process.stdout, "at_eof") and callable(process.stdout.at_eof) and process.stdout.at_eof() is True:
                    break
                line = await process.stdout.readline()
                if not line:
                    break

                line_counter += 1
                session.lines_received += 1
                session.bytes_received += len(line.encode("utf-8", errors="replace"))

                # Velocity calculation every 1.0 second
                now = time.time()
                elapsed = now - session._last_calc_time
                if elapsed >= 1.0:
                    delta_lines = session.lines_received - session._last_calc_lines
                    session.velocity = round(delta_lines / elapsed, 1)
                    session._last_calc_time = now
                    session._last_calc_lines = session.lines_received

                # Parse entry
                entry = parse_log_line(line, session.config.name, line_counter)
                session.ring_buffer.append(entry)

                if not session._paused:
                    try:
                        on_entry(entry)
                    except Exception as exc:
                        logger.warning("Error in on_entry callback for stream %s: %s", stream_id, exc)

        except asyncio.CancelledError:
            logger.debug("Stream reader task cancelled for %s", stream_id)
        except Exception as exc:
            err_str = str(exc)
            if "keepalive" in err_str.lower() or "connection lost" in err_str.lower() or "closed" in err_str.lower():
                logger.warning("Log stream %s disconnected: %s", stream_id, err_str)
            else:
                logger.error("Error reading log stream %s: %s", stream_id, exc)
            session.status = LogStreamStatus.ERROR
            session.error_message = err_str
        finally:
            if session.status != LogStreamStatus.STOPPED:
                if not session.error_message:
                    session.error_message = await _exit_reason(process)
                session.status = LogStreamStatus.ERROR if session.error_message else LogStreamStatus.STOPPED
                session.velocity = 0.0

    def pause_stream(self, stream_id: str) -> None:
        """Pause delivery of new log lines to the UI."""
        session = self._sessions.get(stream_id)
        if session and session.status == LogStreamStatus.STREAMING:
            session._paused = True
            session.status = LogStreamStatus.PAUSED

    def resume_stream(self, stream_id: str) -> None:
        """Resume delivery of new log lines to the UI."""
        session = self._sessions.get(stream_id)
        if session and session.status == LogStreamStatus.PAUSED:
            session._paused = False
            session.status = LogStreamStatus.STREAMING

    def clear_stream_buffer(self, stream_id: str) -> None:
        """Clear buffered entries for a specific stream."""
        session = self._sessions.get(stream_id)
        if session:
            session.ring_buffer.clear()

    async def stop_stream(self, stream_id: str) -> OperationResult:
        """Gracefully terminate a remote log tail process."""
        session = self._sessions.get(stream_id)
        if not session:
            return OperationResult.failure(f"Stream '{stream_id}' not found.")

        session.status = LogStreamStatus.STOPPED
        session.velocity = 0.0

        task = self._tasks.pop(stream_id, None)
        if task and not task.done():
            task.cancel()

        process = session.process
        if process:
            try:
                process.terminate()
                # Give process a moment to exit
                try:
                    await asyncio.wait_for(process.wait(), timeout=0.8)
                except (asyncio.TimeoutError, Exception):
                    process.kill()
            except Exception as exc:
                logger.debug("Process kill exception for stream %s: %s", stream_id, exc)

        return OperationResult.success(f"Stream '{session.config.name}' stopped.")

    async def stop_all_streams(self) -> None:
        """Terminate all active log stream processes (e.g. on disconnect)."""
        stream_ids = list(self._sessions.keys())
        for sid in stream_ids:
            try:
                await self.stop_stream(sid)
            except Exception as exc:
                logger.debug("Error stopping stream %s: %s", sid, exc)
        self._sessions.clear()
        self._tasks.clear()
