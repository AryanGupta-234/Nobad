"""Loopback HTTP server for the web UI: one-time launch code, session cookie, Host/Origin checks, static UI files,
``POST /api/<name>`` and the ``GET /events`` SSE stream.

Ported from NOBAD VPN (apps/vpn/nobadvpn/server.py), same security model:
* The page never contains a secret. The window opens ``/?k=<one-time code>``; the server swaps the code for an
  HttpOnly, SameSite=Strict cookie and redirects to ``/``. Any other local program gets a "locked" page.
* Only ``127.0.0.1:<port>`` / ``localhost:<port>`` Host headers and same-origin requests are served, which blocks
  DNS rebinding and cross-site requests from a browser.
* CSP ``script-src 'self'``: no inline scripts, so injected markup can't run code or drive the API. Fonts may also come
  from ``data:`` (Monaco embeds its icon font that way; a font can't run code), and workers from ``blob:``
  (Monaco starts its workers from a blob that loads the real, same-origin worker file; only script already allowed
  on the page can create one)."""
from __future__ import annotations

import hmac
import json
import os
import queue
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app_web import bus
from app_web.api import api_post
from app_web.handlers import register_all

UI_DIR = Path(__file__).resolve().parent / "ui"
# Monaco is shared with the classic window (resources/editor/*.html), so it lives once under resources/ and is
# mounted here; no CDN (issue #30).
MONACO_DIR = Path(__file__).resolve().parents[1] / "resources" / "editor" / "vendor" / "monaco"
MOUNTS = {"vendor/monaco": MONACO_DIR}
COOKIE = "nbfb_s"
LAUNCH_TTL = 600            # seconds a launch code stays valid; each code works once
MAX_BODY = 1_000_000
DRAIN_LIMIT = 16_000_000   # bytes read (and dropped) from a refused request so the reply arrives
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "connect-src 'self'; font-src 'self' data:; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
CTYPES = {
    ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2",
}
_STATIC_OK = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-][A-Za-z0-9_\-.]*)*\.(js|css|json|svg|png|ico|woff2)$")
LOCKED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>NOBAD File Bridge</title>
<style>body{margin:0;display:grid;place-items:center;min-height:100vh;background:#08090d;color:#f4f4f6;
font:15px/1.6 system-ui,"Segoe UI",sans-serif}main{max-width:420px;padding:24px;text-align:center}
h1{font-size:20px;margin:0 0 8px}p{color:#a0a1aa;margin:0}</style></head><body><main><h1>NOBAD File Bridge</h1>
<p>This page only opens from NOBAD File Bridge itself. Start the app to use it.</p></main></body></html>"""


class Session:
    """Per-process secrets: the cookie value and the outstanding one-time launch codes."""

    def __init__(self) -> None:
        self.cookie = secrets.token_urlsafe(24)
        self._codes: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue_code(self) -> str:
        code = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            for old in [k for k, t in self._codes.items() if now - t > LAUNCH_TTL]:
                del self._codes[old]
            self._codes[code] = now
        return code

    def redeem(self, code: str) -> bool:
        if not code:
            return False
        with self._lock:
            issued = self._codes.pop(code, None)
        return issued is not None and time.monotonic() - issued <= LAUNCH_TTL


def index_ui_files(root: Path) -> dict[str, Path]:
    """Every file the UI may serve, by its URL path (``screens/settings.js``), found once at start-up.

    A request only picks an entry from this index; it never builds a filesystem path, so ``..``, absolute paths,
    links or odd encodings can't reach anything else."""
    root = root.resolve()
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == "index.html" or _STATIC_OK.match(rel):
            files[rel] = path
    return files


class Handler(BaseHTTPRequestHandler):
    server_version = "NOBAD-File-Bridge"
    server: "BridgeServer"

    def log_message(self, *_args: Any) -> None:
        pass

    # ---- checks
    def _origin_ok(self) -> bool:
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _authed(self) -> bool:
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == COOKIE and value:
                return hmac.compare_digest(value, self.server.session.cookie)
        return False

    # ---- responses
    def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        elif ctype.startswith("image/svg"):
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox")
        self.end_headers()
        self.wfile.write(body)

    def _page(self, qs: dict[str, list[str]]) -> None:
        code = qs.get("k", [""])[0]
        if code:
            if not self.server.session.redeem(code):
                return self._send(403, LOCKED_PAGE, "text/html; charset=utf-8")
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{COOKIE}={self.server.session.cookie}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if not self._authed():
            return self._send(403, LOCKED_PAGE, "text/html; charset=utf-8")
        raw = self.server.read_ui("index.html")
        if raw is None:
            return self._send(404, {"ok": False})
        html = raw.decode("utf-8").replace("__VER__", self.server.ctx.version)
        return self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        url = urlparse(self.path)
        if not self._origin_ok():
            return self._send(403, {"ok": False})
        if url.path == "/":
            return self._page(parse_qs(url.query))
        if url.path == "/favicon.ico":
            raw = self.server.read_ui("brand/favicon.ico")
            return self._send(200, raw, CTYPES[".ico"]) if raw else self._send(404, {"ok": False})
        if url.path.startswith("/static/"):
            rel = url.path[len("/static/"):]
            raw = self.server.read_ui(rel) if rel != "index.html" else None
            if raw is None:
                return self._send(404, {"ok": False})
            return self._send(200, raw, CTYPES.get(os.path.splitext(rel)[1].lower(), "application/octet-stream"))
        if not self._authed():
            return self._send(401, {"ok": False, "error": "auth"})
        if url.path == "/events":
            return self._events()
        return self._send(404, {"ok": False})

    def _events(self) -> None:
        q = bus.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": hello\n\n")
            self.wfile.flush()
            while not self.server.stopping.is_set():
                try:
                    self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ka\n\n")
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            bus.unsubscribe(q)

    def _reject(self, code: int, body: Any) -> None:
        """Refuse a POST after reading its body: closing with unread data makes Windows send RST instead of the reply."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        remaining = min(max(length, 0), DRAIN_LIMIT)
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass
        self.close_connection = True
        self._send(code, body)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        url = urlparse(self.path)
        if not self._origin_ok():
            return self._reject(403, {"ok": False})
        if not self._authed():
            return self._reject(401, {"ok": False, "error": "auth"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return self._reject(413, {"ok": False, "error": "Request too large."})
        try:
            raw = self.rfile.read(length) if length > 0 else b""
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = {}
        if not url.path.startswith("/api/"):
            return self._send(404, {"ok": False})
        try:
            return self._send(200, api_post(url.path[len("/api/"):], body if isinstance(body, dict) else {}, self.server.ctx))
        except Exception as exc:
            bus.log(f"Internal error in {url.path}: {exc}", "bad", "server")
            return self._send(500, {"ok": False, "error": bus.scrub(exc)})


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    # A page load opens ~25 connections at once (one per file; HTTP/1.0 closes each). The default listen backlog of
    # 5 overflowed when the server was busy (live logs, transfers), and Windows refused the extra connections: a
    # random script then failed to load after a reload.
    request_queue_size = 128

    def __init__(self, ctx: Any) -> None:
        register_all()
        super().__init__(("127.0.0.1", 0), Handler)
        self.ctx = ctx
        self.session = Session()
        self.stopping = threading.Event()
        self.ui_files = index_ui_files(UI_DIR)
        for prefix, root in MOUNTS.items():
            if root.is_dir():
                self.ui_files.update({f"{prefix}/{rel}": path for rel, path in index_ui_files(root).items() if rel != "index.html"})

    def read_ui(self, rel: str) -> bytes | None:
        path = self.ui_files.get(rel)
        if path is None:
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def launch_url(self) -> str:
        """URL that opens the UI and signs the window in once. Make a fresh one for every window."""
        return f"{self.base_url}/?k={self.session.issue_code()}"

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, name="web-ui-server", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.stopping.set()
        self.shutdown()
        self.server_close()
