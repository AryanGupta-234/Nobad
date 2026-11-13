"""Loopback HTTP server: per-launch token, Host/Origin checks, static UI files, SSE event stream.

Authentication. The UI pages never contain a secret. NOBAD opens its windows with a one-time launch code
(`launch_url`), which the server swaps for an HttpOnly, SameSite=Strict session cookie and then redirects to the
clean URL. Any other local program that requests a page gets a "locked" page with no secret in it. The process-to-
process client (lifecycle.py) uses the X-Token header with the token from the admin-only instance file."""
import hmac
import json
import os
import queue
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import logbus
from .api import api_post
from .const import APP_VER, UI_DIR
from .ctx import ctx

TOKEN = secrets.token_urlsafe(24)       # header token for NOBAD's own processes (instance file, admin-only)
SESSION = secrets.token_urlsafe(24)     # cookie value for the UI windows, never written into a page
COOKIE = "nobad_s"
LAUNCH_TTL = 600                        # seconds a launch code stays valid; each code works once
_launch = {}
_launch_lock = threading.Lock()


def issue_launch_code():
    code = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _launch_lock:
        for k in [k for k, t in _launch.items() if now - t > LAUNCH_TTL]:
            del _launch[k]
        _launch[code] = now
    return code


def _redeem_launch_code(code):
    if not code:
        return False
    with _launch_lock:
        t = _launch.pop(code, None)
    return t is not None and time.monotonic() - t <= LAUNCH_TTL


def launch_url(base_url, path="/"):
    """URL that opens a UI page and signs the window in once. Create a fresh one for every window you open."""
    return f"{base_url}{path}?k={issue_launch_code()}"


LOCKED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>NOBAD VPN</title>
<style>body{margin:0;display:grid;place-items:center;min-height:100vh;background:#07090d;color:#e8eaf0;
font:15px/1.6 system-ui,Segoe UI,sans-serif}main{max-width:420px;padding:24px;text-align:center}
h1{font-size:20px;margin:0 0 8px}p{color:#9aa3b2;margin:0}</style></head><body><main><h1>NOBAD VPN</h1>
<p>This page only opens from NOBAD VPN itself. Open NOBAD VPN from the Start menu or the tray icon.</p>
</main></body></html>"""
_STATIC_OK = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*\.(js|css|json|svg|png|ico)$")
# No inline scripts (#7): an injected <script> or on*= handler can't run, so an XSS can't drive the API through
# the session cookie. Inline styles stay allowed (style attributes); they can't run code.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'none'")


# Fixed types for the only extensions _STATIC_OK allows. `mimetypes` reads the Windows registry on first use (~90 ms,
# and every request of the page's first burst waited for it, so each UI file took ~340 ms to arrive).
CTYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
          ".ico": "image/x-icon"}
_ui_cache = {}          # rel path -> (mtime, bytes): the UI is ~300 KB and served again for every window
_ui_lock = threading.Lock()


def _read_ui(rel):
    path = os.path.normpath(os.path.join(UI_DIR, rel))
    if not path.startswith(os.path.normpath(UI_DIR) + os.sep):
        return None
    try:
        mtime = os.stat(path).st_mtime_ns
        hit = _ui_cache.get(rel)
        if hit and hit[0] == mtime:
            return hit[1]
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    with _ui_lock:
        _ui_cache[rel] = (mtime, data)
    return data


def preload_ui():
    """Read every UI file once, in the background at start-up, so the first window paints from memory."""
    for dirpath, _dirs, files in os.walk(UI_DIR):
        for fn in files:
            if fn.endswith((".html", ".js", ".css", ".png", ".ico", ".svg")):
                _read_ui(os.path.relpath(os.path.join(dirpath, fn), UI_DIR).replace(os.sep, "/"))


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

    def _cookie_session(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _auth(self, qs=None):
        t = self.headers.get("X-Token", "")
        if t and hmac.compare_digest(t, TOKEN):
            return True
        c = self._cookie_session()
        return bool(c) and hmac.compare_digest(c, SESSION)

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
        elif ctype.startswith("image/svg"):    # remote SVGs (TMDB logos) can carry script: never let them run here
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox")
        self.end_headers()
        self.wfile.write(body)

    def _page(self, name, path, qs):
        code = qs.get("k", [""])[0]
        if code:
            if not _redeem_launch_code(code):
                return self._send(403, LOCKED_PAGE, "text/html; charset=utf-8")
            self.send_response(303)
            self.send_header("Location", path)
            self.send_header("Set-Cookie", f"{COOKIE}={SESSION}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._auth():
            return self._send(403, LOCKED_PAGE, "text/html; charset=utf-8")
        raw = _read_ui(name)
        if raw is None:
            return self._send(404, {"ok": False})
        html = raw.decode("utf-8").replace("__VER__", APP_VER)
        self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._origin_ok():
            return self._send(403, {"ok": False})
        if u.path == "/":
            return self._page("index.html", "/", qs)
        if u.path == "/mini":
            return self._page("mini.html", "/mini", qs)
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
            return self._send(200, raw, CTYPES.get(os.path.splitext(rel)[1].lower(), "application/octet-stream"))
        if u.path.startswith("/si/img/"):          # TMDB posters/logos via a validating, caching proxy (CSP stays 'self')
            if not self._auth():                   # only NOBAD's own windows: no fetching or disk-filling for others
                return self._send(401, {"ok": False, "error": "auth"})
            parts = u.path.split("/")
            if len(parts) == 5:
                from .streamintel.api_handlers import get as _si
                data = _si().image(parts[3], parts[4])
                if data:
                    ctype = "image/png" if data[:8].startswith(bytes([0x89]) + b"PNG") else "image/svg+xml" if b"<svg" in data[:200] else "image/jpeg"
                    return self._send(200, data, ctype)
            return self._send(404, {"ok": False})
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
    threading.Thread(target=preload_ui, name="ui-preload", daemon=True).start()
    return srv
