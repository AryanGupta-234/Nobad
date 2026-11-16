from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
import inspect
import logging
import shlex
import socket
import time
from typing import Any
import uuid

from core.result import OperationResult

logger = logging.getLogger("remote_file_manager.tunnel_manager")


class TunnelType(StrEnum):
    LOCAL = "local"           # -L: Local port forwarded to remote destination
    REMOTE = "remote"         # -R: Remote server forwards connections to local service
    DYNAMIC_SOCKS5 = "socks5" # -D: Dynamic SOCKS5 application proxy


class TunnelStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    CONNECTING = "connecting"


@dataclass(slots=True)
class TunnelConfig:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "New Tunnel"
    tunnel_type: TunnelType = TunnelType.LOCAL
    local_host: str = "127.0.0.1"
    local_port: int = 5433
    remote_host: str = "127.0.0.1"
    remote_port: int = 5432
    auto_connect: bool = False
    description: str = ""
    category: str = "custom"  # database, web, cache, proxy, custom

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tunnel_type": str(self.tunnel_type),
            "local_host": self.local_host,
            "local_port": self.local_port,
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "auto_connect": self.auto_connect,
            "description": self.description,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TunnelConfig":
        tt = TunnelType(data.get("tunnel_type", "local"))
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            name=data.get("name", "Tunnel"),
            tunnel_type=tt,
            local_host=data.get("local_host", "127.0.0.1"),
            local_port=int(data.get("local_port", 8080)),
            remote_host=data.get("remote_host", "127.0.0.1"),
            remote_port=int(data.get("remote_port", 80)),
            auto_connect=bool(data.get("auto_connect", False)),
            description=data.get("description", ""),
            category=data.get("category", "custom"),
        )


@dataclass(slots=True)
class TunnelStreamInfo:
    client_addr: str
    target_addr: str
    duration_sec: float = 0.0
    bytes_in: int = 0
    bytes_out: int = 0
    status: str = "active"


@dataclass(slots=True)
class TunnelSessionInfo:
    config: TunnelConfig
    status: TunnelStatus = TunnelStatus.INACTIVE
    error_msg: str | None = None
    listener: Any = None
    started_at: float = 0.0
    bytes_in: int = 0
    bytes_out: int = 0
    latency_ms: float = 0.0
    active_connections: int = 0
    streams: list[TunnelStreamInfo] = field(default_factory=list)


DEFAULT_TUNNEL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "preset-postgres",
        "name": "PostgreSQL Forward",
        "tunnel_type": TunnelType.LOCAL,
        "local_host": "127.0.0.1",
        "local_port": 5433,
        "remote_host": "127.0.0.1",
        "remote_port": 5432,
        "description": "Secure loopback access to remote PostgreSQL server on port 5433",
        "category": "database",
    },
    {
        "id": "preset-mysql",
        "name": "MySQL / MariaDB",
        "tunnel_type": TunnelType.LOCAL,
        "local_host": "127.0.0.1",
        "local_port": 3307,
        "remote_host": "127.0.0.1",
        "remote_port": 3306,
        "description": "Forward local 3307 to remote MySQL server without public exposure",
        "category": "database",
    },
    {
        "id": "preset-redis",
        "name": "Redis In-Memory Cache",
        "tunnel_type": TunnelType.LOCAL,
        "local_host": "127.0.0.1",
        "local_port": 6380,
        "remote_host": "127.0.0.1",
        "remote_port": 6379,
        "description": "Direct CLI or Redis Insight debugging via local port 6380",
        "category": "cache",
    },
    {
        "id": "preset-mongodb",
        "name": "MongoDB Replica / Standalone",
        "tunnel_type": TunnelType.LOCAL,
        "local_host": "127.0.0.1",
        "local_port": 27018,
        "remote_host": "127.0.0.1",
        "remote_port": 27017,
        "description": "Forward MongoDB daemon to 127.0.0.1:27018 for Compass",
        "category": "database",
    },
    {
        "id": "preset-web",
        "name": "Web Staging / Backend",
        "tunnel_type": TunnelType.LOCAL,
        "local_host": "127.0.0.1",
        "local_port": 8080,
        "remote_host": "127.0.0.1",
        "remote_port": 80,
        "description": "Preview internal Nginx / Apache site on http://localhost:8080",
        "category": "web",
    },
    {
        "id": "preset-socks5",
        "name": "SOCKS5 Dynamic Proxy",
        "tunnel_type": TunnelType.DYNAMIC_SOCKS5,
        "local_host": "127.0.0.1",
        "local_port": 1080,
        "remote_host": "0.0.0.0",
        "remote_port": 0,
        "description": "Route browser or curl traffic dynamically through remote server",
        "category": "proxy",
    },
]


class SSHTunnelManager:
    """
    Manages SSH Port Forwarding tunnels (Local, Remote, Dynamic SOCKS5)
    using native asyncssh forwarding listeners.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, TunnelSessionInfo] = {}

    def get_session(self, tunnel_id: str) -> TunnelSessionInfo | None:
        return self._sessions.get(tunnel_id)

    def get_all_sessions(self) -> dict[str, TunnelSessionInfo]:
        return dict(self._sessions)

    @staticmethod
    def is_port_in_use(host: str, port: int) -> bool:
        """
        Check if a local port is already bound by another process.
        Supports both IPv4 and IPv6 without false-positives from SO_REUSEADDR.
        """
        if port <= 0 or port > 65535:
            return True
        check_host = "127.0.0.1" if host in ("localhost", "") else host
        try:
            addrinfo = socket.getaddrinfo(
                check_host, port, socket.AF_UNSPEC, socket.SOCK_STREAM, 0, socket.AI_PASSIVE
            )
        except socket.gaierror:
            addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (check_host, port))]

        for family, socktype, proto, _, sockaddr in addrinfo:
            try:
                with socket.socket(family, socktype, proto) as s:
                    s.bind(sockaddr)
                    return False
            except OSError:
                return True
        return False

    @classmethod
    def find_next_available_port(cls, start_port: int, host: str = "127.0.0.1") -> int:
        """
        Find the next unallocated TCP port starting from start_port up to 65535.
        """
        port = max(1024, start_port)
        while port < 65535:
            if not cls.is_port_in_use(host, port):
                return port
            port += 1
        return start_port

    @staticmethod
    def test_socket_ping(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float, str]:
        """
        Test if a TCP socket responds, measuring latency in milliseconds.
        Returns (is_reachable, latency_ms, status_message).
        """
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                latency = (time.perf_counter() - t0) * 1000.0
                return True, round(latency, 2), f"Reachable in {latency:.1f}ms"
        except socket.timeout:
            return False, 0.0, f"Timed out after {timeout:.1f}s"
        except ConnectionRefusedError:
            return False, 0.0, "Connection refused (socket closed or filtered)"
        except Exception as e:
            return False, 0.0, f"Error: {e}"

    @staticmethod
    def generate_openssh_command(
        config: TunnelConfig,
        host: str = "example.com",
        username: str = "ubuntu",
        port: int = 22,
        identity_file: str | None = None,
    ) -> str:
        """
        Generate equivalent OpenSSH CLI command string with safe shell escaping.
        """
        parts = ["ssh", "-N"]

        if config.tunnel_type == TunnelType.LOCAL:
            parts.extend(["-L", f"{config.local_host}:{config.local_port}:{config.remote_host}:{config.remote_port}"])
        elif config.tunnel_type == TunnelType.REMOTE:
            parts.extend(["-R", f"{config.remote_host}:{config.remote_port}:{config.local_host}:{config.local_port}"])
        elif config.tunnel_type == TunnelType.DYNAMIC_SOCKS5:
            parts.extend(["-D", f"{config.local_host}:{config.local_port}"])

        if identity_file:
            parts.extend(["-i", shlex.quote(identity_file)])

        if port and port != 22:
            parts.extend(["-p", str(port)])

        parts.append(f"{shlex.quote(username)}@{shlex.quote(host)}")
        return " ".join(parts)

    def _unwrap_connection(self, connection: Any) -> Any:
        """Extract underlying asyncssh connection object if wrapped."""
        if hasattr(connection, "forward_local_port"):
            return connection
        if hasattr(connection, "raw_connection") and connection.raw_connection is not None:
            return connection.raw_connection
        if hasattr(connection, "_client") and connection._client is not None:
            return connection._client
        if hasattr(connection, "_conn") and connection._conn is not None:
            return connection._conn
        return connection

    async def start_tunnel(self, connection: Any, config: TunnelConfig) -> OperationResult:
        """
        Open the requested tunnel listener on the active SSH connection.
        """
        conn = self._unwrap_connection(connection)
        if conn is None:
            return OperationResult.failure("SSH connection is not active or available.")

        if not hasattr(conn, "forward_local_port"):
            return OperationResult.failure(
                "Active connection protocol does not support SSH port forwarding (requires SSH or SFTP).",
                suggested_fix="Connect to an SSH or SFTP host to enable port forwarding.",
            )

        session = self._sessions.get(config.id)
        if session and session.status == TunnelStatus.ACTIVE and session.listener is not None:
            return OperationResult.success(
                f"Tunnel '{config.name}' is already active.",
                data=session,
            )

        if session and session.listener is not None:
            await self.stop_tunnel(config.id)

        # Guard against port collisions for local listen endpoints
        if config.tunnel_type in (TunnelType.LOCAL, TunnelType.DYNAMIC_SOCKS5):
            bind_check_host = "127.0.0.1" if config.local_host in ("localhost", "") else config.local_host
            if self.is_port_in_use(bind_check_host, config.local_port):
                suggested_port = self.find_next_available_port(config.local_port + 1, bind_check_host)
                return OperationResult.failure(
                    f"Port collision: Local port {config.local_port} is already in use by another application.",
                    suggested_fix=f"Choose a different local port (e.g., {suggested_port}).",
                    technical_details=f"port_collision: host={bind_check_host} port={config.local_port} suggested={suggested_port}",
                )

        if not session:
            session = TunnelSessionInfo(config=config)
            self._sessions[config.id] = session

        session.status = TunnelStatus.CONNECTING
        session.error_msg = None

        try:
            listener: Any = None
            if config.tunnel_type == TunnelType.LOCAL:
                call_res = conn.forward_local_port(
                    config.local_host,
                    config.local_port,
                    config.remote_host,
                    config.remote_port,
                )
                listener = await call_res if inspect.isawaitable(call_res) else call_res
            elif config.tunnel_type == TunnelType.REMOTE:
                call_res = conn.forward_remote_port(
                    config.remote_host,
                    config.remote_port,
                    config.local_host,
                    config.local_port,
                )
                listener = await call_res if inspect.isawaitable(call_res) else call_res
            elif config.tunnel_type == TunnelType.DYNAMIC_SOCKS5:
                call_res = conn.forward_socks(
                    config.local_host,
                    config.local_port,
                )
                listener = await call_res if inspect.isawaitable(call_res) else call_res

            session.listener = listener
            session.status = TunnelStatus.ACTIVE
            session.started_at = time.time()
            session.error_msg = None

            # Quick latency check to the newly opened endpoint
            if config.tunnel_type in (TunnelType.LOCAL, TunnelType.DYNAMIC_SOCKS5):
                reachable, lat, _ = self.test_socket_ping(config.local_host, config.local_port)
                if reachable:
                    session.latency_ms = lat

            return OperationResult.success(
                f"Tunnel '{config.name}' is now active on port {config.local_port}.",
                data=session,
            )

        except Exception as exc:
            session.status = TunnelStatus.ERROR
            session.error_msg = str(exc)
            logger.exception("Failed to start tunnel %s", config.name)
            return OperationResult.failure(
                f"Failed to start tunnel: {exc}",
                technical_details=str(exc),
            )

    async def stop_tunnel(self, tunnel_id: str) -> OperationResult:
        """
        Close an active tunnel listener and update session state.
        """
        session = self._sessions.get(tunnel_id)
        if not session or not session.listener:
            if session:
                session.status = TunnelStatus.INACTIVE
                session.listener = None
            return OperationResult.success(f"Tunnel {tunnel_id} is already stopped.")

        try:
            listener = session.listener
            if inspect.isawaitable(listener):
                listener = await listener

            if hasattr(listener, "close"):
                listener.close()
            elif hasattr(listener, "__aexit__"):
                try:
                    await listener.__aexit__(None, None, None)
                except Exception:
                    pass

            if hasattr(listener, "wait_closed"):
                res = listener.wait_closed()
                if inspect.isawaitable(res):
                    await res

            session.listener = None
            session.status = TunnelStatus.INACTIVE
            session.active_connections = 0
            return OperationResult.success(f"Tunnel '{session.config.name}' stopped successfully.")
        except Exception as exc:
            session.status = TunnelStatus.ERROR
            session.error_msg = str(exc)
            return OperationResult.failure(f"Error stopping tunnel: {exc}")

    async def stop_all_tunnels(self) -> None:
        """
        Gracefully stop all currently running tunnels.
        """
        for tid in list(self._sessions.keys()):
            await self.stop_tunnel(tid)
