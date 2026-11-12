"""Security properties of the loopback server: Host/Origin/token checks, static-file whitelist."""
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


def test_index_has_token_and_csp(srv):
    st, h, body = req(srv, "GET", "/")
    assert st == 200 and server.TOKEN.encode() in body and b"__TOKEN__" not in body
    assert "script-src 'self' 'unsafe-inline'" in h["Content-Security-Policy"] and "frame-ancestors 'none'" in h["Content-Security-Policy"]


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
