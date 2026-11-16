"""Event bus for the web UI: fan-out to every open SSE stream, a small log ring, and secret scrubbing.

Ported from NOBAD VPN's logbus.py. Two additions for a file manager:
* ``scrub`` also hides passwords, tokens, private keys and ``user:pass@`` URLs, because remote output and error
  messages can contain them.
* ``Coalescer`` merges high-rate events (transfer progress, terminal output) into one event per key every
  ``interval`` seconds, so a fast transfer can't flood the page."""
from __future__ import annotations

import collections
import json
import queue
import re
import threading
import time
from collections.abc import Callable
from typing import Any

_subs: list[queue.Queue[str]] = []
_subs_lock = threading.Lock()
_log_ring: collections.deque[dict[str, str]] = collections.deque(maxlen=300)

_SECRET_FIELD = re.compile(
    r"((?:pass(?:word|wd|phrase)?|secret|token|api[_-]?key|private[_-]?key|authorization)[\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,}]+)",
    re.I,
)
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)[^@\s/]+@", re.I)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)


def scrub(text: object) -> str:
    """Never let secrets reach a log line, a toast or the page."""
    value = _PRIVATE_KEY.sub("(hidden private key)", str(text))
    value = _URL_CREDENTIALS.sub(r"\1(hidden)@", value)
    return _SECRET_FIELD.sub(r"\1(hidden)", value)


def has_subscribers() -> bool:
    with _subs_lock:
        return bool(_subs)


def broadcast(kind: str, payload: Any) -> None:
    msg = json.dumps({"type": kind, "payload": payload}, default=str)
    with _subs_lock:
        subscribers = list(_subs)
    for q in subscribers:
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass        # a stalled page loses events rather than blocking the backend


def subscribe(maxsize: int = 500) -> queue.Queue[str]:
    q: queue.Queue[str] = queue.Queue(maxsize=maxsize)
    with _subs_lock:
        _subs.append(q)
    return q


def unsubscribe(q: queue.Queue[str]) -> None:
    with _subs_lock:
        if q in _subs:
            _subs.remove(q)


def log(message: object, level: str = "info", source: str = "app") -> dict[str, str]:
    """Add a line to the activity log (shown in the dock) and push it to open pages."""
    entry = {"ts": time.strftime("%H:%M:%S"), "level": level, "source": source, "msg": scrub(message)}
    _log_ring.append(entry)
    broadcast("log", entry)
    return entry


def recent_log() -> list[dict[str, str]]:
    return list(_log_ring)


def clear_log() -> None:
    _log_ring.clear()


class Coalescer:
    """Keeps only the latest payload per key and broadcasts a batch at most every ``interval`` seconds."""

    def __init__(self, kind: str, interval: float = 0.05, send: Callable[[str, Any], None] = broadcast) -> None:
        self.kind = kind
        self.interval = interval
        self._send = send
        self._pending: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def push(self, key: str, payload: Any) -> None:
        with self._lock:
            self._pending[key] = payload
            if self._timer is None:
                self._timer = threading.Timer(self.interval, self.flush)
                self._timer.daemon = True
                self._timer.start()

    def flush(self) -> None:
        with self._lock:
            batch, self._pending = self._pending, {}
            self._timer = None
        if batch:
            self._send(self.kind, list(batch.values()))
