"""Terminal tabs for the web UI: SSH shells on the connected server and local shells (ConPTY / PTY).

The sessions are the same ones the classic window uses (terminal/ssh_terminal.py, terminal/local_pty_terminal.py).
Their output callbacks can fire on the asyncio thread or on a reader thread, so output goes through
``OutputBuffer``: chunks are appended (never replaced, unlike the progress Coalescer) and sent as one ``term.out``
event per terminal every 16 ms. Output is never logged: it is the user's screen, not an app message."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from app_web import bus
from app_web.files import FileError, run_sync
from core.async_runtime import AsyncRuntime
from terminal.local_pty_terminal import LocalPtyTerminalSession
from terminal.ssh_terminal import SSHTerminalSession

MAX_TERMINALS = 12
MAX_INPUT = 64 * 1024
MAX_PENDING = 2 * 1024 * 1024          # per terminal; beyond this the oldest output is dropped (a runaway `yes`)
FLUSH_INTERVAL = 0.016
HISTORY = 256 * 1024                # kept per terminal so a reloaded window can redraw it


class OutputBuffer:
    def __init__(self, send=bus.broadcast) -> None:  # type: ignore[no-untyped-def]
        self._send = send
        self._pending: dict[str, list[str]] = {}
        self._sizes: dict[str, int] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def push(self, term_id: str, data: str) -> None:
        with self._lock:
            chunks = self._pending.setdefault(term_id, [])
            chunks.append(data)
            size = self._sizes.get(term_id, 0) + len(data)
            while size > MAX_PENDING and len(chunks) > 1:
                size -= len(chunks.pop(0))
            self._sizes[term_id] = size
            if self._timer is None:
                self._timer = threading.Timer(FLUSH_INTERVAL, self.flush)
                self._timer.daemon = True
                self._timer.start()

    def flush(self) -> None:
        with self._lock:
            pending, self._pending, self._sizes = self._pending, {}, {}
            self._timer = None
        for term_id, chunks in pending.items():
            self._send("term.out", {"id": term_id, "data": "".join(chunks)})


class Terminal:
    def __init__(self, term_id: str, kind: str, title: str, session: Any, profile_id: str | None) -> None:
        self.id = term_id
        self.kind = kind                 # "remote" | "local"
        self.title = title
        self.session = session
        self.profile_id = profile_id
        self.alive = True
        self._history: list[str] = []
        self._history_size = 0
        self._lock = threading.Lock()

    def remember(self, data: str) -> None:
        with self._lock:
            self._history.append(data)
            self._history_size += len(data)
            while self._history_size > HISTORY and len(self._history) > 1:
                self._history_size -= len(self._history.pop(0))

    def history(self) -> str:
        with self._lock:
            return "".join(self._history)[-HISTORY:]

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "title": self.title, "alive": self.alive}


class TerminalService:
    def __init__(self) -> None:
        self.terminals: dict[str, Terminal] = {}
        self.output = OutputBuffer()

    def list(self) -> list[dict[str, Any]]:
        return [t.summary() for t in self.terminals.values()]

    def open(self, kind: str, *, connection: Any = None, cwd: str | None = None, shell: str | None = None,
             startup: str | None = None, cols: int = 100, rows: int = 30) -> dict[str, Any]:
        if len(self.terminals) >= MAX_TERMINALS:
            raise FileError(f"Close a terminal first (up to {MAX_TERMINALS} at a time).")
        if kind == "remote":
            if connection is None or getattr(connection, "raw_connection", None) is None:
                raise FileError("Terminals on a server need an SSH or SFTP connection.")
            profile = connection.profile
            session: Any = SSHTerminalSession(connection, cwd=cwd or None, startup_command=startup or None)
            title, profile_id = profile.name, profile.id
        elif kind == "local":
            session = LocalPtyTerminalSession(cwd=cwd or None, shell_path=shell or None, startup_command=startup or None)
            title, profile_id = "This computer", None
        else:
            raise FileError("Unknown terminal type.")
        term_id = uuid.uuid4().hex[:12]
        term = Terminal(term_id, kind, title, session, profile_id)

        def on_output(data: str) -> None:
            term.remember(data)
            self.output.push(term_id, data)

        def on_exit() -> None:
            term.alive = False
            self.output.flush()
            bus.broadcast("term.exit", {"id": term_id})

        result = run_sync(session.start(on_output, on_exit), timeout=30)
        if not result.ok:
            raise FileError(result.message)
        self.terminals[term_id] = term
        self._submit(session.resize(_clamp(cols, 20, 500), _clamp(rows, 5, 200)))
        return term.summary()

    def get(self, term_id: Any) -> Terminal:
        term = self.terminals.get(term_id) if isinstance(term_id, str) else None
        if term is None:
            raise FileError("That terminal is closed.")
        return term

    def write(self, term_id: Any, data: Any) -> None:
        if not isinstance(data, str) or len(data) > MAX_INPUT:
            raise FileError("Paste less text at a time.")
        term = self.get(term_id)
        if not term.alive:
            raise FileError("This terminal has ended. Open a new one.")
        self._submit(term.session.send(data))

    def resize(self, term_id: Any, cols: Any, rows: Any) -> None:
        term = self.get(term_id)
        self._submit(term.session.resize(_clamp(cols, 20, 500), _clamp(rows, 5, 200)))

    def close(self, term_id: Any) -> None:
        term = self.terminals.pop(term_id, None) if isinstance(term_id, str) else None
        if term is not None:
            self._submit(term.session.close())
            bus.broadcast("term.closed", {"id": term.id})

    def close_for_profile(self, profile_id: str) -> int:
        """Close the server's terminals when its connection goes away."""
        ids = [t.id for t in self.terminals.values() if t.profile_id == profile_id]
        for term_id in ids:
            self.close(term_id)
        return len(ids)

    def close_all(self) -> None:
        for term_id in list(self.terminals):
            self.close(term_id)

    @staticmethod
    def _submit(coro: Any) -> None:
        AsyncRuntime.instance().submit(coro)


def _clamp(value: Any, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return low
