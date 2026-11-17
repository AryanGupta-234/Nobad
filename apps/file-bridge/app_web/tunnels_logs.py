"""SSH tunnels and live logs for the web UI, on ``core.tunnel_manager`` and ``core.log_streamer``.

Tunnels
* Saved in the app database (one settings row), each with the server it belongs to. Started on the current SSH
  connection; all of them close when that connection closes.
* A local or SOCKS forward listens on 127.0.0.1 unless the tunnel explicitly allows other devices: a SOCKS proxy on
  0.0.0.0 would let anyone on the network browse through your server. A reverse forward listens on the server's
  loopback unless it explicitly allows public access.
* Port collisions are checked before starting, with a free port suggested.

Live logs
* ``tail -F`` or ``journalctl -f`` over the connection (``sudo -n`` when asked). Lines are batched every 100 ms per
  stream into ``logs.lines`` (at most 500 per batch; the rest are counted as skipped, and stay in the stream's
  10,000-line buffer for ``logs.tail``). At most 8 streams at once; all stop with the connection.
* A stream that ends by itself reports why (missing file, permission, sudo wanting a password)."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import threading
from typing import Any
from uuid import uuid4

from app_web import bus
from app_web.files import FileError, run_sync
from core.async_runtime import AsyncRuntime
from core.log_streamer import DEFAULT_LOG_PRESETS, LogSourceType, LogStreamConfig, LogStreamManager, LogStreamStatus
from core.services_manager import validate_unit_name
from core.tunnel_manager import DEFAULT_TUNNEL_PRESETS, SSHTunnelManager, TunnelConfig, TunnelStatus, TunnelType

TUNNELS_ROW = "web_ui.tunnels"
MAX_TUNNELS = 50
MAX_STREAMS = 8
BATCH = 500
FLUSH = 0.1
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class TunnelError(FileError):
    pass


def _ssh(session: Any) -> Any:
    current = session.current
    if current is None:
        raise TunnelError("Connect to a server first.")
    caps = getattr(current, "capabilities", None)
    if caps is not None and not caps.can_exec_command:
        raise TunnelError("This needs an SSH connection.")
    return current


def _port(value: Any, label: str, *, allow_zero: bool = False) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise TunnelError(f"{label} must be a number.") from None
    if not (0 if allow_zero else 1) <= port <= 65535:
        raise TunnelError(f"{label} must be between 1 and 65535.")
    return port


def _host(value: Any, label: str) -> str:
    host = (value or "").strip() if isinstance(value, str) else ""
    if not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9.\-:_\[\]]+", host):
        raise TunnelError(f"{label} isn't a valid host name or address.")
    return host


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


# ---------------------------------------------------------------- tunnels
class TunnelService:
    def __init__(self, app_data: Any, session: Any) -> None:
        self.app_data = app_data
        self.session = session
        self.manager = SSHTunnelManager()
        self._on: Any = None                       # the connection the running tunnels belong to
        session.on_closed.append(lambda _pid: self._closed())

    def _load(self) -> list[dict[str, Any]]:
        with self.app_data.session_factory() as s:
            stored = self.app_data.settings(s).get(TUNNELS_ROW)
        items = stored.get("value") if isinstance(stored, dict) else None
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def _store(self, items: list[dict[str, Any]]) -> None:
        with self.app_data.session_factory() as s:
            self.app_data.settings(s).set(TUNNELS_ROW, {"value": items})
            s.commit()

    def presets(self) -> list[dict[str, Any]]:
        return [{**p, "tunnel_type": str(p["tunnel_type"])} for p in DEFAULT_TUNNEL_PRESETS]

    def clean(self, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, dict):
            raise TunnelError("Fill in the tunnel.")
        try:
            kind = TunnelType(spec.get("type") or "local")
        except ValueError:
            raise TunnelError("Choose the kind of tunnel.") from None
        name = spec.get("name") if isinstance(spec.get("name"), str) else ""
        name = name.strip()[:80] or "Tunnel"
        allow_lan, allow_public = spec.get("allow_lan") is True, spec.get("allow_public") is True
        local_host = _host(spec.get("local_host") or "127.0.0.1", "Address on this computer")
        if kind != TunnelType.REMOTE and not _is_loopback(local_host) and not allow_lan:
            raise TunnelError("This tunnel would be open to other devices on your network. Use 127.0.0.1, or tick "
                              "\"Let other devices on my network use it\".")
        remote_host = _host(spec.get("remote_host") or "127.0.0.1", "Address on the server side")
        if kind == TunnelType.REMOTE and not _is_loopback(remote_host) and not allow_public:
            raise TunnelError("This would ask the server to accept connections from anywhere. Use 127.0.0.1, or tick "
                              "\"Let anyone who can reach the server use it\".")
        return {
            "id": spec.get("id") if isinstance(spec.get("id"), str) and re.fullmatch(r"[A-Za-z0-9-]{1,40}", spec.get("id")) else uuid4().hex[:10],
            "name": name, "type": kind.value, "local_host": local_host, "local_port": _port(spec.get("local_port"), "Port on this computer"),
            "remote_host": remote_host,
            "remote_port": 0 if kind == TunnelType.DYNAMIC_SOCKS5 else _port(spec.get("remote_port"), "Port on the server side"),
            "allow_lan": allow_lan, "allow_public": allow_public,
            "profile_id": spec.get("profile_id") if isinstance(spec.get("profile_id"), str) else
                          (self.session.current.profile.id if self.session.current is not None else None),
            "description": (spec.get("description") if isinstance(spec.get("description"), str) else "")[:200],
        }

    def _config(self, item: dict[str, Any]) -> TunnelConfig:
        return TunnelConfig(id=item["id"], name=item["name"], tunnel_type=TunnelType(item["type"]), local_host=item["local_host"],
                            local_port=item["local_port"], remote_host=item["remote_host"], remote_port=item["remote_port"],
                            description=item.get("description", ""))

    def list(self) -> dict[str, Any]:
        current = self.session.current
        profile_id = current.profile.id if current is not None else None
        items = []
        for item in self._load():
            run = self.manager.get_session(item["id"]) if self._on is not None and self._on is current else None
            status = run.status.value if run else "inactive"
            items.append({**item, "status": status, "error": bus.scrub(run.error_msg) if run and run.error_msg else None,
                          "since": run.started_at if run and run.status == TunnelStatus.ACTIVE else None,
                          "latency_ms": run.latency_ms if run else None,
                          "mine": not item.get("profile_id") or item.get("profile_id") == profile_id,
                          "ssh": self._openssh(item, current)})
        return {"tunnels": items, "presets": self.presets()}

    def _openssh(self, item: dict[str, Any], connection: Any) -> str:
        profile = getattr(connection, "profile", None)
        return SSHTunnelManager.generate_openssh_command(self._config(item), host=getattr(profile, "host", "server"),
                                                         username=getattr(profile, "username", "user"),
                                                         port=int(getattr(profile, "port", 22) or 22))

    def save(self, spec: Any) -> dict[str, Any]:
        item = self.clean(spec)
        items = self._load()
        if item["id"] in {i["id"] for i in items}:
            run = self.manager.get_session(item["id"])
            if run and run.status == TunnelStatus.ACTIVE:
                raise TunnelError("Stop the tunnel before changing it.")
            items = [item if i["id"] == item["id"] else i for i in items]
        else:
            if len(items) >= MAX_TUNNELS:
                raise TunnelError("That's a lot of tunnels. Delete some first.")
            items.append(item)
        self._store(items)
        return item

    def delete(self, tunnel_id: Any) -> None:
        self.stop(tunnel_id, quiet=True)
        items = [i for i in self._load() if i["id"] != tunnel_id]
        self._store(items)

    def start(self, tunnel_id: Any) -> dict[str, Any]:
        connection = _ssh(self.session)
        item = next((i for i in self._load() if i["id"] == tunnel_id), None)
        if item is None:
            raise TunnelError("That tunnel no longer exists.")
        item = self.clean(item)                           # stored values are checked again before use
        if self._on is not connection:
            self._on = connection
        result = run_sync(self.manager.start_tunnel(connection, self._config(item)), timeout=30)
        if not result.ok:
            raise TunnelError(result.message + (f" {result.suggested_fix}" if result.suggested_fix else ""))
        where = f"{item['local_host']}:{item['local_port']}" if item["type"] != "remote" else f"{item['remote_host']}:{item['remote_port']} on the server"
        bus.log(f"Tunnel {item['name']} is open on {where}.", "ok", "tunnels")
        self._announce()
        return {"message": f"Open on {where}."}

    def stop(self, tunnel_id: Any, *, quiet: bool = False) -> None:
        if not isinstance(tunnel_id, str) or self.manager.get_session(tunnel_id) is None:
            if quiet:
                return
            raise TunnelError("That tunnel isn't open.")
        result = run_sync(self.manager.stop_tunnel(tunnel_id), timeout=15)
        if not result.ok and not quiet:
            raise TunnelError(result.message)
        self._announce()

    def test(self, tunnel_id: Any) -> dict[str, Any]:
        item = next((i for i in self._load() if i["id"] == tunnel_id), None)
        if item is None or item["type"] == "remote":
            raise TunnelError("Only tunnels that listen on this computer can be tested from here.")
        host = "127.0.0.1" if item["local_host"] in ("0.0.0.0", "localhost") else item["local_host"]
        ok, ms, message = SSHTunnelManager.test_socket_ping(host, item["local_port"])
        return {"ok": ok, "ms": ms, "message": message}

    def _closed(self) -> None:
        # May run on the runtime loop itself (a new connection replacing the old one), so hand the work to the loop
        # instead of waiting for it here.
        self._on = None
        if self.manager.get_all_sessions():
            async def stop() -> None:
                await self.manager.stop_all_tunnels()
                self._announce()
            AsyncRuntime.instance().submit(stop())
        self._announce()

    def _announce(self) -> None:
        bus.broadcast("tunnels.changed", {})


# ---------------------------------------------------------------- live logs
class LogsService:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.manager = LogStreamManager()
        self._pending: dict[str, list[dict[str, Any]]] = {}
        self._skipped: dict[str, int] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._configs: dict[str, LogStreamConfig] = {}
        session.on_closed.append(lambda _pid: self.stop_all())

    def presets(self) -> list[dict[str, Any]]:
        return [{**p, "source_type": str(p["source_type"])} for p in DEFAULT_LOG_PRESETS]

    def _config(self, spec: Any) -> LogStreamConfig:
        if not isinstance(spec, dict):
            raise TunnelError("Choose a log.")
        source = spec.get("source") or "file"
        if source not in {"file", "journal"}:
            raise TunnelError("Choose a file or a systemd unit.")
        name = (spec.get("name") if isinstance(spec.get("name"), str) else "")[:80].strip()
        try:
            lines = max(0, min(2000, int(spec.get("lines", 150))))
        except (TypeError, ValueError):
            lines = 150
        if source == "file":
            path = spec.get("path") if isinstance(spec.get("path"), str) else ""
            if not path.startswith("/") or "\0" in path or "\n" in path or len(path) > 1024:
                raise TunnelError("Enter the full path of the log file, like /var/log/nginx/error.log.")
            return LogStreamConfig(id=uuid4().hex[:10], name=name or path.rsplit("/", 1)[-1], source_type=LogSourceType.FILE,
                                   target_path=path, bootstrap_lines=lines, use_sudo=spec.get("sudo") is True)
        try:
            unit = validate_unit_name(str(spec.get("unit") or ""))
        except ValueError as exc:
            raise TunnelError(str(exc)) from None
        return LogStreamConfig(id=uuid4().hex[:10], name=name or unit, source_type=LogSourceType.JOURNAL, unit_name=unit,
                               bootstrap_lines=lines, use_sudo=spec.get("sudo") is True)

    def _summary(self, sid: str) -> dict[str, Any] | None:
        s = self.manager.get_session(sid)
        if s is None:
            return None
        c = s.config
        return {"id": sid, "name": c.name, "source": c.source_type.value, "path": c.target_path if c.source_type == LogSourceType.FILE else c.unit_name,
                "status": s.status.value, "lines": s.lines_received, "rate": s.velocity, "sudo": c.use_sudo,
                "error": bus.scrub(s.error_message) if s.error_message else None}

    def list(self) -> dict[str, Any]:
        return {"streams": [x for x in (self._summary(sid) for sid in list(self._configs)) if x], "presets": self.presets()}

    def start(self, spec: Any) -> dict[str, Any]:
        connection = _ssh(self.session)
        live = [sid for sid in self._configs if (s := self.manager.get_session(sid)) and s.status in (LogStreamStatus.STREAMING, LogStreamStatus.PAUSED)]
        if len(live) >= MAX_STREAMS:
            raise TunnelError(f"At most {MAX_STREAMS} logs can be followed at once. Stop one first.")
        config = self._config(spec)
        raw = getattr(connection, "_connection", None) or connection
        result = run_sync(self.manager.start_stream(config, raw, lambda entry: self._push(config.id, entry)), timeout=30)
        if not result.ok:
            raise TunnelError(result.message)
        self._configs[config.id] = config
        self._watch(config.id)
        bus.broadcast("logs.changed", {})
        return self._summary(config.id) or {}

    def _watch(self, sid: str) -> None:
        """Report when a stream ends by itself (the reader loop sets the reason)."""
        async def wait() -> None:
            while True:
                await asyncio.sleep(0.5)
                s = self.manager.get_session(sid)
                if s is None or s.status in (LogStreamStatus.ERROR, LogStreamStatus.STOPPED):
                    self._flush()
                    bus.broadcast("logs.changed", {})
                    if s is not None and s.status == LogStreamStatus.ERROR:
                        bus.log(f"Log {s.config.name} stopped: {bus.scrub(s.error_message or '')}", "warn", "logs")
                    return
        AsyncRuntime.instance().submit(wait())

    def _push(self, sid: str, entry: Any) -> None:
        row = {"t": entry.timestamp, "lvl": entry.level, "text": bus.scrub(entry.text), "n": entry.line_number,
               "status": entry.status_code}
        with self._lock:
            rows = self._pending.setdefault(sid, [])
            rows.append(row)
            if len(rows) > BATCH:
                drop = len(rows) - BATCH
                del rows[:drop]
                self._skipped[sid] = self._skipped.get(sid, 0) + drop
            if self._timer is None:
                self._timer = threading.Timer(FLUSH, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, {}
            skipped, self._skipped = self._skipped, {}
            self._timer = None
        for sid, rows in pending.items():
            bus.broadcast("logs.lines", {"id": sid, "rows": rows, "skipped": skipped.get(sid, 0)})

    def tail(self, sid: Any, count: Any = 1000) -> list[dict[str, Any]]:
        s = self.manager.get_session(sid) if isinstance(sid, str) else None
        if s is None:
            raise TunnelError("That log isn't open.")
        try:
            n = max(1, min(10000, int(count)))
        except (TypeError, ValueError):
            n = 1000
        return [{"t": e.timestamp, "lvl": e.level, "text": bus.scrub(e.text), "n": e.line_number, "status": e.status_code}
                for e in list(s.ring_buffer)[-n:]]

    def pause(self, sid: Any, paused: Any) -> None:
        if not isinstance(sid, str) or self.manager.get_session(sid) is None:
            raise TunnelError("That log isn't open.")
        (self.manager.pause_stream if paused is True else self.manager.resume_stream)(sid)
        bus.broadcast("logs.changed", {})

    def stop(self, sid: Any, *, remove: bool = False) -> None:
        if not isinstance(sid, str) or sid not in self._configs:
            raise TunnelError("That log isn't open.")
        run_sync(self.manager.stop_stream(sid), timeout=10)
        if remove:
            self._configs.pop(sid, None)
        bus.broadcast("logs.changed", {})

    def stop_all(self) -> None:
        """On disconnect; may run on the runtime loop, so the stopping is handed to it, not waited for."""
        self._configs.clear()
        if self.manager.get_active_sessions():
            AsyncRuntime.instance().submit(self.manager.stop_all_streams())
        bus.broadcast("logs.changed", {})

