"""Offline endpoint geolocation: the compact range file, the lookup, and how the engine uses it (no network)."""
import ipaddress
import os

import pytest

from nobadvpn import engine as _engine
from nobadvpn import geoip

REAL_GEO_REFRESH = _engine.Tunnel.geo_refresh        # the `win` fixture stubs it out

SAMPLE = """1.0.0.0,1.0.0.255,AU
1.0.1.0,1.0.3.255,CN
5.62.40.0,5.62.43.255,NL
45.87.212.0,45.87.215.255,DE
146.70.205.0,146.70.205.255,JP
185.159.156.0,185.159.159.255,CH
2001:db8::,2001:db8:ffff:ffff:ffff:ffff:ffff:ffff,ZZ
2a07:b944::,2a07:b944:ffff:ffff:ffff:ffff:ffff:ffff,CH
"""


@pytest.fixture
def db(tmp_path):
    src = tmp_path / "dbip-country-lite.csv"
    src.write_text(SAMPLE.replace("2001:db8::,2001:db8:ffff:ffff:ffff:ffff:ffff:ffff,ZZ\n", ""), encoding="ascii")
    out = tmp_path / "geoip-country.bin"
    geoip.compact(str(src), str(out))
    return geoip.Db(str(out))


def test_known_ranges(db):
    assert db.country("1.0.0.1") == "AU"
    assert db.country("1.0.2.200") == "CN"
    assert db.country("146.70.205.2") == "JP"
    assert db.country("45.87.215.255") == "DE"
    assert db.country("185.159.157.20") == "CH"
    assert db.country("2a07:b944::2:1") == "CH"


def test_gaps_private_and_bad_input_are_unknown(db):
    for ip in ("1.0.4.0", "10.2.0.1", "192.168.1.1", "127.0.0.1", "fd00::2", "::1", "not an ip", "", None,
               "999.1.1.1", "146.70.205.2; calc"):
        assert db.country(ip) is None, ip


def test_compact_file_merges_sorts_and_rejects_junk(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("2.0.0.0,2.0.0.255,FR\n1.0.0.0,1.0.0.255,au\njunk line\n3.0.0.0,2.0.0.0,US\n"
                   "4.0.0.0,4.0.0.255,X1\n2.0.1.0,2.0.1.255,FR\n", encoding="ascii")
    out = tmp_path / "o.bin"
    n = geoip.compact(str(src), str(out))
    assert n == 2                                          # AU, and the two FR ranges merged; junk and bad ranges dropped
    d = geoip.Db(str(out))
    assert d.country("2.0.1.9") == "FR" and d.country("1.0.0.9") == "AU" and d.country("4.0.0.1") is None


def test_a_damaged_file_is_unknown_not_an_error(tmp_path):
    p = tmp_path / "bad.bin"
    p.write_bytes(geoip.MAGIC + bytes([255, 255, 255, 127]))
    assert geoip.Db(str(p)).country("8.8.8.8") is None


def test_missing_database_is_quietly_unknown(tmp_path):
    d = geoip.Db(str(tmp_path / "nothing.bin"))
    assert d.country("146.70.205.2") is None
    assert not d.available


def test_bundled_path_is_inside_the_app():
    p = geoip.default_path()
    assert os.path.basename(p) == "geoip-country.bin"
    assert "nobadvpn" in p


def test_engine_places_servers_offline_without_any_lookup(win, monkeypatch, tmp_path, db):
    """ip_lookup off (the default): no network; the endpoint's country comes from the bundled file."""
    from nobadvpn.ctx import ctx
    from nobadvpn import engine
    monkeypatch.setattr(geoip, "_db", db)
    monkeypatch.setattr(engine.Tunnel, "_ipinfo", staticmethod(lambda path: pytest.fail("no online lookup")))
    monkeypatch.setattr(engine.Tunnel, "_resolve", lambda self, h: ["146.70.205.2"])
    ctx.settings.set("ip_lookup", False)
    ctx.tunnel.geo = {}
    REAL_GEO_REFRESH(ctx.tunnel)                                   # start-up: no lookup, nothing known yet
    assert "vpn.example.com" not in ctx.tunnel.geo
    REAL_GEO_REFRESH(ctx.tunnel, True)                             # an import resolves it
    g = ctx.tunnel.geo["vpn.example.com"]
    assert g == {"country": "JP", "source": "offline"}
    st = ctx.tunnel.state()
    assert st["regions"][0]["geo"]["country"] == "JP"


def test_engine_leaves_unknown_endpoints_unknown(win, monkeypatch, db):
    from nobadvpn.ctx import ctx
    from nobadvpn import engine
    monkeypatch.setattr(geoip, "_db", db)
    monkeypatch.setattr(engine.Tunnel, "_resolve", lambda self, h: ["10.9.8.7"])
    ctx.settings.set("ip_lookup", False)
    ctx.tunnel.geo = {}
    REAL_GEO_REFRESH(ctx.tunnel, True)
    assert "vpn.example.com" not in ctx.tunnel.geo            # not cached: a later database may know it


def test_ipv6_parsing_matches_ipaddress():
    for ip in ("2a07:b944::2:1", "::ffff:1.2.3.4", "2001:db8::1"):
        assert geoip._key(ip) == (6, int(ipaddress.ip_address(ip)))
    assert geoip._key("1.2.3.4") == (4, int(ipaddress.ip_address("1.2.3.4")))


def test_start_up_places_from_the_last_known_address_without_dns(win, monkeypatch, db):
    from nobadvpn.ctx import ctx
    from nobadvpn import engine
    monkeypatch.setattr(geoip, "_db", db)
    monkeypatch.setattr(engine.Tunnel, "_resolve", lambda self, h: pytest.fail("no DNS lookup at start-up"))
    ctx.settings.set("ip_lookup", False)
    ctx.tunnel.geo = {}
    ctx.tunnel._ep_cache["vpn.example.com"] = (0.0, ["45.87.212.9"])     # what an earlier connect found
    REAL_GEO_REFRESH(ctx.tunnel)
    assert ctx.tunnel.geo["vpn.example.com"]["country"] == "DE"
