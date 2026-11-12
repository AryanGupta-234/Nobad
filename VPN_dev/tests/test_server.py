"""Security properties of the loopback server: launch codes and session cookie, Host/Origin/token checks,
static-file whitelist."""
import http.client
import json
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
    assert "script-src 'self' 'unsafe-inline'" in h["Content-Security-Policy"] and "frame-ancestors 'none'" in h["Content-Security-Policy"]
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
    st, h, _body = req(srv, "GET", "/si/img/w92/abcdef.svg")
    assert st == 200 and h["Content-Type"] == "image/svg+xml"
    assert "sandbox" in h["Content-Security-Policy"] and "default-src 'none'" in h["Content-Security-Policy"]
