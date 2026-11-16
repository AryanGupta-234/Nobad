"""Web UI server: sign-in, request checks, static files, API and the event stream (modelled on NOBAD VPN's tests)."""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
from pathlib import Path

import pytest

from app_web import bus
from app_web.context import AppContext
from app_web.server import COOKIE, UI_DIR, BridgeServer


@pytest.fixture
def server(tmp_path: Path):
    srv = BridgeServer(AppContext.create(tmp_path / "app.sqlite3"))
    srv.start()
    yield srv
    srv.stop()


def request(srv, method, path, *, body=None, headers=None, cookie=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    hdrs = {"Host": host or f"127.0.0.1:{srv.server_address[1]}"}
    if cookie:
        hdrs["Cookie"] = f"{COOKIE}={cookie}"
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=hdrs)
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res, data


def sign_in(srv) -> str:
    code = srv.launch_url().split("?k=", 1)[1]
    res, _ = request(srv, "GET", f"/?k={code}")
    assert res.status == 303
    match = re.search(rf"{COOKIE}=([^;]+)", res.getheader("Set-Cookie"))
    assert match
    return match.group(1)


def api(srv, cookie, name, body=None):
    res, data = request(srv, "POST", f"/api/{name}", body=body or {}, cookie=cookie)
    return res.status, json.loads(data)


# ---------------------------------------------------------------- sign-in
def test_launch_code_signs_in_once(server) -> None:
    code = server.launch_url().split("?k=", 1)[1]

    first, _ = request(server, "GET", f"/?k={code}")
    second, body = request(server, "GET", f"/?k={code}")

    assert first.status == 303 and first.getheader("Location") == "/"
    cookie = first.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert second.status == 403 and b"only opens from NOBAD File Bridge" in body


def test_page_and_api_need_the_session_cookie(server) -> None:
    page, body = request(server, "GET", "/")
    post, _ = request(server, "POST", "/api/app.info", body={})
    events, _ = request(server, "GET", "/events")
    wrong, _ = request(server, "POST", "/api/app.info", body={}, cookie="not-the-cookie")

    assert page.status == 403 and b"NOBAD File Bridge" in body
    assert post.status == 401 and events.status == 401 and wrong.status == 401


def test_page_has_strict_csp_and_no_inline_scripts(server) -> None:
    cookie = sign_in(server)
    res, body = request(server, "GET", "/", cookie=cookie)

    csp = res.getheader("Content-Security-Policy")
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp
    assert res.getheader("X-Content-Type-Options") == "nosniff"
    html = body.decode()
    assert "__VER__" not in html
    for tag in re.findall(r"<script\b[^>]*>", html, flags=re.I):
        assert 'src="/static/' in tag, tag
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I), "no inline event handlers"


# ---------------------------------------------------------------- request checks
def test_foreign_host_header_is_refused(server) -> None:
    cookie = sign_in(server)
    res, _ = request(server, "GET", "/", cookie=cookie, host="evil.example:80")
    assert res.status == 403


def test_cross_origin_post_is_refused(server) -> None:
    cookie = sign_in(server)
    res, _ = request(server, "POST", "/api/settings.set", body={"id": "web_ui.theme", "value": "light"}, cookie=cookie,
                     headers={"Origin": "http://evil.example"})
    assert res.status == 403


def test_oversized_request_is_refused(server) -> None:
    cookie = sign_in(server)
    res, _ = request(server, "POST", "/api/app.info", body={"x": "a" * 1_100_000}, cookie=cookie)
    assert res.status == 413


# ---------------------------------------------------------------- static files
@pytest.mark.parametrize("path", ["tokens.css", "core.js", "screens/settings.js", "brand/nobad-logo-light.png"])
def test_ui_files_are_served(server, path: str) -> None:
    res, _ = request(server, "GET", f"/static/{path}")
    assert res.status == 200


@pytest.mark.parametrize("path", ["../server.py", "..%2Fserver.py", "screens/../../server.py", ".hidden.js", "index.html",
                                  "screens/.x.js", "core.py"])
def test_static_paths_cannot_escape_or_serve_other_types(server, path: str) -> None:
    res, _ = request(server, "GET", f"/static/{path}")
    assert res.status == 404


def test_every_file_the_page_loads_exists() -> None:
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="/static/([^"]+)"', html):
        assert (UI_DIR / ref).is_file(), ref


# ---------------------------------------------------------------- API
def test_api_reports_app_info_and_unknown_actions(server) -> None:
    cookie = sign_in(server)
    status, info = api(server, cookie, "app.info")
    _, unknown = api(server, cookie, "does.not.exist")

    assert status == 200 and info["ok"] and info["data"]["name"] == "NOBAD File Bridge"
    assert unknown == {"ok": False, "error": "Unknown action."}


def test_settings_are_validated_and_saved(server) -> None:
    cookie = sign_in(server)
    _, saved = api(server, cookie, "settings.set", {"id": "terminal.font_size", "value": "16"})
    _, too_big = api(server, cookie, "settings.set", {"id": "terminal.font_size", "value": 400})
    _, bad_choice = api(server, cookie, "settings.set", {"id": "web_ui.theme", "value": "neon"})
    _, unknown = api(server, cookie, "settings.set", {"id": "nope", "value": 1})
    _, schema = api(server, cookie, "settings.schema")

    assert saved == {"ok": True, "data": {"id": "terminal.font_size", "value": 16}}
    assert not too_big["ok"] and "8 to 40" in too_big["error"]
    assert not bad_choice["ok"] and not unknown["ok"]
    assert schema["data"]["values"]["terminal.font_size"] == 16


def test_events_stream_delivers_broadcasts(server) -> None:
    cookie = sign_in(server)
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request("GET", "/events", headers={"Host": f"127.0.0.1:{server.server_address[1]}", "Cookie": f"{COOKIE}={cookie}"})
    res = conn.getresponse()
    assert res.status == 200 and res.getheader("Content-Type") == "text/event-stream"
    assert res.fp.readline().startswith(b": hello")
    res.fp.readline()

    def send_later() -> None:
        time.sleep(0.2)
        bus.broadcast("ping", {"n": 1})

    threading.Thread(target=send_later, daemon=True).start()
    line = res.fp.readline().decode()
    conn.close()

    assert line.startswith("data: ")
    assert json.loads(line[len("data: "):]) == {"type": "ping", "payload": {"n": 1}}


def test_ui_index_holds_only_servable_files(tmp_path) -> None:
    from app_web.server import index_ui_files

    (tmp_path / "index.html").write_text("x")
    (tmp_path / "app.js").write_text("x")
    (tmp_path / "secret.py").write_text("x")
    (tmp_path / ".env").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "style.css").write_text("x")

    assert set(index_ui_files(tmp_path)) == {"index.html", "app.js", "sub/style.css"}
