"""Loopback HTTP server: per-launch token, Host/Origin checks, static UI files, SSE event stream."""
import hmac
import json
import mimetypes
import os
import queue
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import logbus
from .api import api_post
from .const import APP_VER, UI_DIR
from .ctx import ctx

TOKEN = secrets.token_urlsafe(24)
_STATIC_OK = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*\.(js|css|json|svg|png|ico)$")
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'none'")


def _read_ui(rel):
    path = os.path.normpath(os.path.join(UI_DIR, rel))
    if not path.startswith(os.path.normpath(UI_DIR) + os.sep):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "Nobad"

    def log_message(self, *a):
        pass

    def _origin_ok(self):
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        o = self.headers.get("Origin")
        return not o or o in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _auth(self, qs=None):
        t = self.headers.get("X-Token") or (qs or {}).get("t", [""])[0]
        return hmac.compare_digest(t, TOKEN)

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _page(self, name):
        raw = _read_ui(name)
        if raw is None:
            return self._send(404, {"ok": False})
        html = raw.decode("utf-8").replace("__TOKEN__", TOKEN).replace("__VER__", APP_VER)
        self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._origin_ok():
            return self._send(403, {"ok": False})
        if u.path == "/":
            return self._page("index.html")
        if u.path == "/mini":
            return self._page("mini.html")
        if u.path == "/favicon.ico":
            raw = _read_ui("brand/nobad.ico")
            return self._send(200, raw, "image/x-icon") if raw else self._send(404, {"ok": False})
        if u.path.startswith("/static/"):
            rel = u.path[len("/static/"):]
            if not _STATIC_OK.match(rel):
                return self._send(404, {"ok": False})
            raw = _read_ui(rel)
            if raw is None:
                return self._send(404, {"ok": False})
            ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            if ctype in ("text/javascript", "application/javascript", "text/css", "application/json"):
                ctype += "; charset=utf-8"
            return self._send(200, raw, ctype)
        if u.path == "/api/ping":
            return self._send(200, {"app": "nobad-vpn", "ver": APP_VER})
        if not self._auth(qs):
            return self._send(401, {"ok": False, "error": "auth"})
        if u.path == "/api/state":
            return self._send(200, ctx.tunnel.state())
        if u.path == "/events":
            return self._sse()
        self._send(404, {"ok": False})

    def _sse(self):
        q = logbus.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": hello\n\n")
            self.wfile.flush()
            while not ctx.quit_event.is_set():
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {msg}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ka\n\n")
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            logbus.unsubscribe(q)

    def _reject(self, code, body):
        """Refuse a POST without leaving its body unread: closing a socket with unread data makes Windows send RST,
        so the client would see 'connection aborted' instead of the status code."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if 0 < n <= 400_000:
            try:
                self.rfile.read(n)
            except OSError:
                pass
        self.close_connection = True
        return self._send(code, body)

    def do_POST(self):
        u = urlparse(self.path)
        if not self._origin_ok():
            return self._reject(403, {"ok": False})
        if not self._auth():
            return self._reject(401, {"ok": False, "error": "auth"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(min(n, 400_000)) if n > 0 else b""
            body = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}
        if not u.path.startswith("/api/"):
            return self._send(404, {"ok": False})
        try:
            self._send(200, api_post(u.path[5:], body))
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})


def make_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    return srv
