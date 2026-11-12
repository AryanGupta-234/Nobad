from nobadvpn import confparse as cp


def test_parse_basic(sample):
    i = cp.parse_conf_text(sample)
    assert i["host"] == "vpn.example.com" and i["port"] == 51820
    assert i["addrs"] == ["10.2.0.2/32", "fd00::2/128"]
    assert i["full"] and i["v6"] and i["dns"] and not i["mtu"] and not i["keepalive"]


def test_parse_ipv6_endpoint():
    t = "[Interface]\nAddress=10.0.0.2/32\n[Peer]\nEndpoint = [2001:db8::1]:51820\nAllowedIPs=::/0\n"
    i = cp.parse_conf_text(t)
    assert i["host"] == "2001:db8::1" and i["port"] == 51820


def test_validate_ok(sample):
    r = cp.validate_conf(sample)
    assert r["ok"], r["errors"]


def test_validate_catches_problems(sample):
    bad = sample.replace("51820", "99999").replace("10.2.0.2/32", "10.2.0.2/99")
    r = cp.validate_conf(bad)
    assert not r["ok"]
    assert any("Endpoint" in e for e in r["errors"]) and any("Address" in e for e in r["errors"])


def test_validate_requires_sections():
    r = cp.validate_conf("[Interface]\nPrivateKey = abc\n")
    assert not r["ok"]
    assert any("Peer" in e for e in r["errors"])


def test_script_hooks_rejected_from_untrusted(sample):
    t = sample.replace("DNS = 10.2.0.1", "DNS = 10.2.0.1\nPostUp = calc.exe")
    assert cp.validate_conf(t)["ok"]                       # local file: warning only
    assert any("PostUp" in w for w in cp.validate_conf(t)["warnings"])
    r = cp.validate_conf(t, untrusted_source=True)         # URL / QR: refused
    assert not r["ok"] and any("PostUp" in e for e in r["errors"])


def test_tuned_adds_mtu_keepalive_and_dns():
    t = "[Interface]\nPrivateKey = x\nAddress = 10.0.0.2/32\n[Peer]\nEndpoint = h:1\n"
    info = cp.parse_conf_text(t)
    out = cp.tuned_conf_text(t, info, stream=True, dns_fallback="1.1.1.1, 1.0.0.1")
    assert "MTU = 1380" in out and "PersistentKeepalive = 25" in out and "DNS = 1.1.1.1, 1.0.0.1" in out


def test_tuned_respects_existing(sample):
    info = cp.parse_conf_text(sample)
    out = cp.tuned_conf_text(sample, info, stream=False, dns_fallback="9.9.9.9")
    assert "9.9.9.9" not in out and "MTU" not in out


def test_redact_and_restore(sample, keys):
    priv, _pub, psk = keys
    red = cp.redact_conf(sample)
    assert priv not in red and psk not in red and red.count(cp.KEY_MASK) == 2
    restored = cp.restore_masked(red, sample)
    assert priv in restored and psk in restored


def test_dpapi_roundtrip(tmp_path, sample, fake_dpapi):
    p = tmp_path / "Home.conf.dpapi"
    cp.write_conf_text(str(p), sample)
    raw = p.read_bytes()
    assert b"PrivateKey" not in raw
    assert cp.read_conf_text(str(p)).replace("\r\n", "\n") == sample
    assert cp.stem_of("Home.conf.dpapi") == "Home" and cp.stem_of("x.txt") is None


def test_dpapi_name_binding(tmp_path, sample, fake_dpapi):
    p = tmp_path / "A.conf.dpapi"
    cp.write_conf_text(str(p), sample)
    q = tmp_path / "B.conf.dpapi"
    q.write_bytes(p.read_bytes())
    import pytest
    from nobadvpn import dpapi
    with pytest.raises(dpapi.DpapiError):
        cp.read_conf_text(str(q))
