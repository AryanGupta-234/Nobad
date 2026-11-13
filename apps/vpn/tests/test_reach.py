"""reach.py: adaptive routes for NOBAD's own requests (alternate official hostnames, encrypted-DNS lookups),
route memory, the off switch, and that HTTP answers never trigger a re-route. No real network."""
import io
import types
import urllib.error
import urllib.request

import pytest

from nobadvpn import reach


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(reach, "_PATH", str(tmp_path / "reach.json"))
    monkeypatch.setattr(reach, "_routes", {})
    monkeypatch.setattr(reach, "_enabled", lambda: True)
    monkeypatch.setattr(reach, "system_resolve", lambda host: ["93.184.216.34"])
    yield


def reset():
    return urllib.error.URLError(ConnectionResetError(10054, "reset"))


@pytest.mark.parametrize("ip,bad", [("0.0.0.0", True), ("127.0.0.1", True), ("10.1.2.3", True), ("192.168.1.1", True),
                                    ("169.254.1.1", True), ("::1", True), ("nonsense", True), ("104.21.40.212", False),
                                    ("2606:4700::6810:28d4", False)])
def test_bogus_dns_answers(ip, bad):
    assert reach.bogus(ip) is bad


def test_direct_route_when_it_works():
    calls = []
    out = reach.urlopen(urllib.request.Request("https://api.tmdb.org/3/x"),
                        _direct=lambda req, timeout=None: calls.append(req.full_url) or Resp(b"ok"))
    assert out.read() == b"ok" and calls == ["https://api.tmdb.org/3/x"]
    assert reach._routes["api.tmdb.org"]["route"] == "direct"


def test_alternate_official_hostname_when_the_name_is_reset_and_route_is_remembered():
    calls = []

    def direct(req, timeout=None):
        calls.append(req.full_url)
        if "api.themoviedb.org" in req.full_url:
            raise reset()
        return Resp(b"alt")
    req = urllib.request.Request("https://api.themoviedb.org/3/movie/1?x=1", headers={"Authorization": "Bearer t"})
    assert reach.urlopen(req, _direct=direct).read() == b"alt"
    assert calls == ["https://api.themoviedb.org/3/movie/1?x=1", "https://api.tmdb.org/3/movie/1?x=1"]
    assert reach._routes["api.themoviedb.org"] == dict(reach._routes["api.themoviedb.org"], route="alt", host="api.tmdb.org")
    calls.clear()
    reach.urlopen(req, _direct=direct)
    assert calls == ["https://api.tmdb.org/3/movie/1?x=1"]                     # learned: no failing attempt first


def test_headers_and_method_survive_the_host_swap():
    seen = []

    def direct(req, timeout=None):
        if "api.themoviedb.org" in req.full_url:
            raise reset()
        seen.append((req.get_method(), req.get_header("Authorization")))
        return Resp(b"")
    reach.urlopen(urllib.request.Request("https://api.themoviedb.org/3/a", headers={"Authorization": "Bearer t"}), _direct=direct)
    assert seen == [("GET", "Bearer t")]


def test_dns_blocked_name_goes_through_encrypted_dns(monkeypatch):
    monkeypatch.setattr(reach, "system_resolve", lambda host: ["0.0.0.0"])          # sinkholed by the network's DNS
    pinned = []
    monkeypatch.setattr(reach, "_pinned_open", lambda req, host, ip, timeout: pinned.append((host, ip)) or Resp(b"doh"))

    def direct(req, timeout=None):
        raise AssertionError("must not go direct to a sinkholed answer")
    out = reach.urlopen(urllib.request.Request("https://ipinfo.io/json"), _direct=direct, _doh=lambda h: ["34.117.59.81"])
    assert out.read() == b"doh" and pinned == [("ipinfo.io", "34.117.59.81")]
    assert reach._routes["ipinfo.io"]["route"] == "doh" and reach._routes["ipinfo.io"]["ip"] == "34.117.59.81"


def test_http_answers_are_not_rerouted():
    calls = []

    def direct(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
    with pytest.raises(urllib.error.HTTPError):
        reach.urlopen(urllib.request.Request("https://api.themoviedb.org/3/a"), _direct=direct, _doh=lambda h: ["1.2.3.4"])
    assert calls == ["https://api.themoviedb.org/3/a"]                           # an auth error is the same everywhere


def test_everything_blocked_raises_the_last_network_error(monkeypatch):
    monkeypatch.setattr(reach, "_pinned_open", lambda *a, **k: (_ for _ in ()).throw(reset()))
    with pytest.raises(urllib.error.URLError):
        reach.urlopen(urllib.request.Request("https://api.themoviedb.org/3/a"),
                      _direct=lambda req, timeout=None: (_ for _ in ()).throw(reset()), _doh=lambda h: ["1.2.3.4"])
    assert "api.themoviedb.org" not in reach._routes


def test_off_switch_and_plain_http_go_direct(monkeypatch):
    monkeypatch.setattr(reach, "_enabled", lambda: False)
    calls = []
    reach.urlopen(urllib.request.Request("https://api.themoviedb.org/3/a"), _direct=lambda req, timeout=None: calls.append(1) or Resp(b""))
    assert calls == [1] and reach._routes == {}
    with pytest.raises(urllib.error.URLError):
        reach.urlopen(urllib.request.Request("https://api.themoviedb.org/3/a"), _direct=lambda req, timeout=None: (_ for _ in ()).throw(reset()))


def test_forget_and_persisted_routes(tmp_path, monkeypatch):
    reach._routes["a.example"] = {"route": "alt", "host": "b.example", "ip": None, "ts": 9e12}
    reach._save()
    monkeypatch.setattr(reach, "_routes", {})
    reach._load()
    assert reach._routes["a.example"]["route"] == "alt"
    reach.forget()
    assert reach._routes == {}


def test_doh_resolve_parses_answers_and_skips_bogus():
    def opener(req, timeout=None):
        if "type=A&" in req.full_url + "&" and "type=AAAA" not in req.full_url:
            return Resp(b'{"Answer":[{"type":5,"data":"x.cdn."},{"type":1,"data":"0.0.0.0"},{"type":1,"data":"104.21.40.212"}]}')
        return Resp(b'{"Answer":[{"type":28,"data":"2606:4700::6810:28d4"}]}')
    assert reach.doh_resolve("example.com", opener=opener) == ["104.21.40.212", "2606:4700::6810:28d4"]


def test_report_explains_routes(monkeypatch):
    def opener(req, timeout=None):
        host = urllib.request.urlparse(req.full_url).hostname
        if host == "api.tmdb.org":
            reach._routes[host] = {"route": "alt", "host": "api.themoviedb.org", "ts": 9e12}
            return Resp(b"")
        if host == "ipinfo.io":
            raise reset()
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
    r = reach.report(opener=opener)
    by = {s["id"]: s for s in r["services"]}
    assert by["tmdb"]["route"] == "alt" and "official alternative" in by["tmdb"]["explain"]
    assert by["ipinfo"]["status"] == "unreachable" and "VPN" in by["ipinfo"]["explain"]
    assert by["wikipedia"]["status"] == "ok"                                   # an HTTP answer proves the route


def test_api_and_settings_are_wired():
    from nobadvpn import api
    from nobadvpn.const import DEFAULTS
    assert "reach_test" in api.HANDLERS and "reach_forget" in api.HANDLERS and DEFAULTS["net_adapt"] is True
    # the service checks and Network Intelligence must keep measuring the direct path
    import inspect
    from nobadvpn import tools
    assert "reach.urlopen" not in inspect.getsource(tools.check_service)
    assert "reach.urlopen" in inspect.getsource(tools.speed_test)
    _ = types
