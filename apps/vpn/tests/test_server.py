"""Security properties of the loopback server: launch codes and session cookie, Host/Origin/token checks,
static-file whitelist."""
import http.client
import json
import os
import shutil
import threading

import pytest

from nobadvpn import app, server


@pytest.fixture(scope="module")
def srv():
    app.init()
    s = server.make_server()
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()


def req(srv, method, path, headers=None, body=None):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": f"127.0.0.1:{port}"}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    return r.status, dict(r.getheaders()), data


def test_page_without_launch_code_is_locked_and_leaks_nothing(srv):
    for path in ("/", "/mini"):
        st, _h, body = req(srv, "GET", path)
        assert st == 403, path
        assert server.TOKEN.encode() not in body and server.SESSION.encode() not in body
        assert b"only opens from NOBAD VPN" in body


def test_launch_code_signs_in_once_with_httponly_cookie(srv):
    code = server.issue_launch_code()
    st, h, body = req(srv, "GET", f"/?k={code}")
    assert st == 303 and h["Location"] == "/" and body == b""
    cookie = h["Set-Cookie"]
    assert cookie.startswith(f"{server.COOKIE}={server.SESSION};")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert req(srv, "GET", f"/?k={code}")[0] == 403                 # a code works only once
    assert req(srv, "GET", "/?k=made-up")[0] == 403


def test_signed_in_page_has_csp_and_no_secret(srv):
    jar = {"Cookie": f"{server.COOKIE}={server.SESSION}"}
    st, h, body = req(srv, "GET", "/", jar)
    assert st == 200 and b"__TOKEN__" not in body and b"__VER__" not in body
    assert server.TOKEN.encode() not in body and server.SESSION.encode() not in body
    assert "script-src 'self';" in h["Content-Security-Policy"] and "unsafe-inline';" not in h["Content-Security-Policy"].split("style-src")[0] and "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert req(srv, "GET", "/mini", jar)[0] == 200


def test_expired_launch_code_is_refused(srv, monkeypatch):
    code = server.issue_launch_code()
    monkeypatch.setattr(server, "LAUNCH_TTL", -1)
    assert req(srv, "GET", f"/?k={code}")[0] == 403


def test_api_accepts_cookie_or_header_only(srv):
    assert req(srv, "GET", "/api/state", {"Cookie": f"{server.COOKIE}={server.SESSION}"})[0] == 200
    assert req(srv, "GET", "/api/state", {"Cookie": f"{server.COOKIE}=wrong"})[0] == 401
    assert req(srv, "GET", f"/api/state?t={server.TOKEN}")[0] == 401          # no secrets in URLs any more
    assert req(srv, "GET", f"/events?t={server.TOKEN}")[0] == 401


def test_api_import_never_allows_script_hooks(srv):
    conf = ("[Interface]\nPrivateKey = " + "A" * 43 + "=\nAddress = 10.0.0.2/32\nPostUp = calc.exe\n\n[Peer]\n"
            "PublicKey = " + "B" * 43 + "=\nEndpoint = 1.2.3.4:51820\nAllowedIPs = 0.0.0.0/0\n")
    body = json.dumps({"name": "hooktest", "content": conf, "untrusted": False}).encode()
    st, _h, data = req(srv, "POST", "/api/import", {"X-Token": server.TOKEN}, body)
    assert st == 200 and json.loads(data)["ok"] is False


def test_dns_rebinding_host_rejected(srv):
    assert req(srv, "GET", "/", {"Host": "evil.example"})[0] == 403


def test_cross_origin_post_rejected(srv):
    st, *_ = req(srv, "POST", "/api/connect", {"Origin": "http://evil.example", "X-Token": server.TOKEN}, b"{}")
    assert st == 403


def test_api_requires_token(srv):
    assert req(srv, "GET", "/api/state")[0] == 401
    assert req(srv, "POST", "/api/panic_reset", body=b"{}")[0] == 401
    assert req(srv, "GET", "/api/state", {"X-Token": server.TOKEN})[0] == 200


def test_static_whitelist_and_traversal(srv):
    assert req(srv, "GET", "/static/app_ext.js")[0] == 200
    assert req(srv, "GET", "/static/brand/nobad-mark.png")[0] == 200
    assert req(srv, "GET", "/static/locales/es.json")[0] == 404          # English only: no locale files ship
    assert req(srv, "GET", "/favicon.ico")[0] == 200
    assert req(srv, "GET", "/static/vendor/jsqr.js")[0] == 200
    for bad in ("/static/../server.py", "/static/..%2fserver.py", "/static/index.html", "/static/brand/../../const.py",
                "/static//etc/passwd", "/static/app_ext.js%00.png"):
        assert req(srv, "GET", bad)[0] == 404, bad


def test_unknown_endpoint_and_bad_input(srv):
    st, _h, body = req(srv, "POST", "/api/nope", {"X-Token": server.TOKEN}, b"{}")
    assert json.loads(body)["ok"] is False
    st, _h, body = req(srv, "POST", "/api/settings", {"X-Token": server.TOKEN}, json.dumps({"key": "dpapi_runtime_ok", "value": False}).encode())
    assert json.loads(body)["ok"] is False
    st, _h, body = req(srv, "POST", "/api/open_url", {"X-Token": server.TOKEN}, json.dumps({"key": "javascript:alert(1)"}).encode())
    assert json.loads(body)["ok"] is False


def test_config_names_cannot_escape_folder(srv):
    from nobadvpn import configstore
    r = configstore.import_text("../../evil", "[Interface]\n")
    assert not r["ok"]
    n = configstore.clean_name("../../evil")
    assert ".." not in n and "/" not in n and "\\" not in n


def test_svg_responses_are_sandboxed(srv, monkeypatch):
    from nobadvpn.streamintel import api_handlers

    class _SI:
        def image(self, size, name):
            return b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    monkeypatch.setattr(api_handlers, "get", lambda: _SI())
    st, h, _body = req(srv, "GET", "/si/img/w92/abcdef.svg", {"Cookie": f"{server.COOKIE}={server.SESSION}"})
    assert st == 200 and h["Content-Type"] == "image/svg+xml"
    assert "sandbox" in h["Content-Security-Policy"] and "default-src 'none'" in h["Content-Security-Policy"]


JAR = {"Cookie": f"{server.COOKIE}={server.SESSION}"}
NAV = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"}


def test_ui_keeps_working_when_its_files_vanish_while_running(srv, monkeypatch, tmp_path):
    """The maintainer's quick view showed `{"ok": false}`: NOBAD 1.5.1 was uninstalled while it kept running, the
    uninstaller deleted every file not in use (the whole ui folder) and the quick view, created on first use, got
    a 404 for /mini. Everything was preloaded at start-up, so the cached copy must keep the windows working."""
    from nobadvpn import const
    ui = tmp_path / "ui"
    shutil.copytree(const.UI_DIR, ui)
    monkeypatch.setattr(server, "UI_DIR", str(ui))
    monkeypatch.setattr(server, "_ui_cache", {})
    server.preload_ui()
    shutil.rmtree(ui)
    st, h, body = req(srv, "GET", "/mini", JAR)
    assert st == 200 and h["Content-Type"].startswith("text/html") and b'id="go"' in body
    assert req(srv, "GET", "/", JAR)[0] == 200
    assert req(srv, "GET", "/static/mini.js", JAR)[0] == 200
    assert req(srv, "GET", "/favicon.ico")[0] == 200


def test_ui_file_changed_on_disk_is_served_fresh(srv, monkeypatch, tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "mini.html").write_text("<p>old __VER__</p>", encoding="utf-8")
    monkeypatch.setattr(server, "UI_DIR", str(ui))
    monkeypatch.setattr(server, "_ui_cache", {})
    assert b"old" in req(srv, "GET", "/mini", JAR)[2]
    (ui / "mini.html").write_text("<p>new __VER__</p>", encoding="utf-8")
    os.utime(ui / "mini.html", ns=(1, 1))                  # a different mtime, whatever the clock resolution
    assert b"new" in req(srv, "GET", "/mini", JAR)[2]


def test_missing_page_file_says_so_in_html(srv, monkeypatch, tmp_path):
    """Never cached and gone: an honest page, not raw JSON."""
    monkeypatch.setattr(server, "UI_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_ui_cache", {})
    st, h, body = req(srv, "GET", "/mini", dict(JAR, **NAV))
    assert st == 404 and h["Content-Type"].startswith("text/html") and b"reinstall" in body.lower()
    assert b'{"ok"' not in body and "script-src 'self'" in h["Content-Security-Policy"]


def test_page_navigation_to_a_non_page_gets_html_back_link(srv):
    """Defence in depth: a window that lands on a non-page URL (a dropped link, an image dragged onto it) shows a way
    back, not Edge's JSON viewer. The link goes to the window's own page."""
    for path, extra, home in (("/nope", {}, b'href="/"'), ("/static/brand/none.png", {}, b'href="/"'),
                              ("/api/window", {}, b'href="/"'),
                              ("/nope", {"Referer": "http://127.0.0.1/mini"}, b'href="/mini"')):
        st, h, body = req(srv, "GET", path, dict(JAR, **NAV, **extra))
        assert st == 404 and h["Content-Type"].startswith("text/html"), path
        assert b"Back to NOBAD VPN" in body and home in body, (path, body)
        assert server.TOKEN.encode() not in body and server.SESSION.encode() not in body
    st, h, body = req(srv, "GET", "/", dict(NAV, Host="evil.example"))      # DNS rebinding: still refused, no JSON
    assert st == 403 and h["Content-Type"].startswith("text/html") and b"Back to NOBAD VPN" in body
    st, h, body = req(srv, "GET", "/nope", dict(JAR, Accept="text/html"))     # old WebView without Sec-Fetch-*
    assert st == 404 and h["Content-Type"].startswith("text/html")
    st, h, body = req(srv, "GET", "/api/state", NAV)                          # not signed in: the locked page
    assert st == 401 and h["Content-Type"].startswith("text/html") and b"only opens from NOBAD VPN" in body


def test_api_and_fetch_callers_still_get_json(srv):
    fetch = {"Accept": "*/*", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors"}
    for path, hdr in (("/nope", JAR), ("/nope", dict(JAR, **fetch)), ("/static/brand/none.png", {"Sec-Fetch-Dest": "image", "Accept": "image/*"}),
                      ("/api/nope", dict(JAR, **fetch))):
        st, h, body = req(srv, "GET", path, hdr)
        assert st == 404 and h["Content-Type"] == "application/json" and json.loads(body) == {"ok": False}, path
    st, h, body = req(srv, "GET", "/", {"Host": "evil.example", "Sec-Fetch-Dest": "empty"})
    assert st == 403 and json.loads(body) == {"ok": False}
    st, _h, body = req(srv, "GET", "/api/state", fetch)                        # auth failure keeps its error key
    assert st == 401 and json.loads(body) == {"ok": False, "error": "auth"}
