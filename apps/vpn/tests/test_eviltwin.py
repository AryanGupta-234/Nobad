"""Evil Twin: parsers, each check, grading, and the auto-VPN rule (all with fakes: nothing touches the network)."""
from nobadvpn import eviltwin as et

NETSH = """
Interface name : Wi-Fi
There are 2 networks currently visible.

SSID 1 : CafeFree
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : aa:bb:cc:00:00:01
         Signal             : 88%
SSID 2 : CafeFree
    Network type            : Infrastructure
    Authentication          : Open
    Encryption              : None
    BSSID 1                 : de:ad:be:ef:00:02
         Signal             : 97%
"""

ARP = """
Interface: 192.168.1.10 --- 0x9
  Internet Address      Physical Address      Type
  192.168.1.1           30-bd-13-2f-00-28     dynamic
  192.168.1.4           9c-97-1b-53-a4-2b     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
"""


def test_parsers():
    nets = et.parse_networks(NETSH)
    assert [(n["ssid"], n["auth"], n["bssids"]) for n in nets] == [
        ("CafeFree", "WPA2-Personal", ["aa:bb:cc:00:00:01"]), ("CafeFree", "Open", ["de:ad:be:ef:00:02"])]
    t = et.parse_arp(ARP)
    assert t == {"192.168.1.10": {"192.168.1.1": "30:bd:13:2f:00:28", "192.168.1.4": "9c:97:1b:53:a4:2b"}}
    assert et.proxy_from_reg("    ProxyEnable    REG_DWORD    0x1\n    ProxyServer    REG_SZ    10.0.0.9:8080\n") == ("10.0.0.9:8080", None)
    assert et.proxy_from_reg("    ProxyEnable    REG_DWORD    0x0\n") == (None, None)


def test_arp_spoof_detected_when_router_mac_is_shared():
    ok = et.arp_spoof_check(et.parse_arp(ARP), "192.168.1.1")
    assert ok["state"] == "pass"
    spoofed = et.parse_arp(ARP.replace("9c-97-1b-53-a4-2b", "30-bd-13-2f-00-28"))
    r = et.arp_spoof_check(spoofed, "192.168.1.1")
    assert r["state"] == "fail" and r["cap"] == "F" and "192.168.1.4" in r["detail"]


def test_evil_twin_and_open_wifi():
    ident = {"name": "CafeFree", "kind": "wifi", "auth": "Open", "bssid": "de:ad:be:ef:00:02", "gw_mac": None}
    sec, twin = et.check_wifi(ident, et.parse_networks(NETSH))
    assert sec["state"] == "fail" and twin["state"] == "fail" and twin["cap"] == "F"
    home = {"name": "Home", "kind": "wifi", "auth": "WPA3-Personal", "bssid": "aa:aa:aa:aa:aa:aa"}
    sec, twin = et.check_wifi(home, [{"ssid": "Home", "auth": "WPA3-Personal", "bssids": ["aa:aa:aa:aa:aa:aa"]}])
    assert sec["state"] == "pass" and twin["state"] == "pass"


def test_router_changed_against_baseline():
    ident = {"name": "Home", "kind": "wired", "gw_mac": "11:22:33:44:55:66"}
    assert et.check_baseline(ident, {})[0]["state"] == "skip"
    assert et.check_baseline(ident, {"Home": {"gw_macs": ["11:22:33:44:55:66"]}})[0]["state"] == "pass"
    r = et.check_baseline(ident, {"Home": {"gw_macs": ["aa:aa:aa:aa:aa:aa"]}})[0]
    assert r["state"] == "warn" and r["cap"] == "C"


class FakeProbes:
    def __init__(self, canary_ok=True, intercepted=False, nx_hijack=False, tls_ok=True):
        self.canary_ok, self.intercepted, self.nx, self.tls_ok = canary_ok, intercepted, nx_hijack, tls_ok

    def interception_test(self, v6=False):
        return {"intercepted": self.intercepted, "probes": [{"target": "192.0.2.53", "answered": self.intercepted, "rcode": "NOERROR"}]}

    def os_resolve(self, name, timeout=5.0):
        if name in et.CANARIES:
            return {"ok": True, "ips": sorted(et.CANARIES[name])[:1] if self.canary_ok else ["10.9.9.9"]}
        if name.startswith("nb"):
            return {"ok": True, "ips": ["10.9.9.9"]} if self.nx else {"ok": False, "error": "no such name"}
        return {"ok": True, "ips": ["104.16.0.1"]}

    def tls_probe(self, ip, sni, timeout=4.0):
        if self.tls_ok:
            return {"tcp_ok": True, "tls_ok": True, "verify_ok": True, "names": [sni]}
        return {"tcp_ok": True, "tls_ok": True, "verify_ok": False, "names": ["proxy.evil.local"], "issuer": "Evil CA"}


class FakeTunnel:
    def __init__(self, connected=False):
        self.connected, self.connecting, self.calls = connected, False, []

    def region_names(self):
        return ["india-mumbai"]

    def has_region(self, n):
        return n == "india-mumbai"

    def connect(self, n):
        self.calls.append(n)


def make(tmp_path, probes=None, ident=None, arp=ARP, settings=None, tunnel=None, scan=()):
    ident = ident or {"name": "Home", "kind": "wired", "auth": None, "bssid": None, "gw_mac": "30:bd:13:2f:00:28"}
    s = {"et_enabled": True, "et_vpn_below": "C", "last_region": "india-mumbai", "trusted_networks": [], "trusted_fingerprints": {}}
    s.update(settings or {})
    return et.EvilTwin(s, tunnel or FakeTunnel(), path=str(tmp_path / "et.json"), ident_fn=lambda: ident,
                       scan_fn=lambda: list(scan), arp_fn=lambda: et.parse_arp(arp), gw_fn=lambda: "192.168.1.1",
                       reg_fn=lambda: "", captive_fn=lambda timeout=4: {"status": "open"}, probes=probes or FakeProbes())


def test_clean_network_grades_A_and_stays_disconnected(tmp_path):
    t = FakeTunnel()
    r = make(tmp_path, tunnel=t).run()
    assert r["grade"] == "A" and r["score"] == 100 and t.calls == []
    assert all(c["state"] in ("pass", "skip") for c in r["checks"])


def test_attacked_network_grades_F_and_turns_vpn_on(tmp_path):
    t = FakeTunnel()
    r = make(tmp_path, probes=FakeProbes(tls_ok=False), tunnel=t).run()
    assert r["grade"] == "F" and r["checks"][0]["id"] == "tls-intercept" and t.calls == ["india-mumbai"]
    assert r["action"] == "connected"


def test_auto_vpn_respects_threshold_and_manual_disconnect(tmp_path):
    t = FakeTunnel()
    g = make(tmp_path, probes=FakeProbes(nx_hijack=True), tunnel=t, settings={"et_vpn_below": "off"})
    assert g.run()["grade"] == "B" and t.calls == []          # 'off' never connects
    g = make(tmp_path, probes=FakeProbes(canary_ok=False, intercepted=True), tunnel=t)
    g.note_manual_disconnect()
    assert g.run()["grade"] in ("D", "F") and t.calls == []   # the user disconnected on purpose
    assert et.below("D", "C") and not et.below("C", "C") and not et.below("F", "off")


def test_connected_vpn_skips_dns_and_https_checks(tmp_path):
    r = make(tmp_path, probes=FakeProbes(tls_ok=False), tunnel=FakeTunnel(connected=True)).run()
    ids = {c["id"] for c in r["checks"]}
    assert "tls-intercept" not in ids and "dns-canary" not in ids and r["grade"] == "A"


def test_attacked_network_is_not_learned_as_baseline(tmp_path):
    g = make(tmp_path, probes=FakeProbes(tls_ok=False))
    g.run()
    assert g._load() == {}
    g = make(tmp_path)
    g.run()
    assert g._load()["Home"]["gw_macs"] == ["30:bd:13:2f:00:28"]


def test_grade_caps():
    assert et.grade_of(95) == "A" and et.grade_of(72) == "C" and et.grade_of(10) == "F"
    assert et.grade_of(95, ["F"]) == "F" and et.grade_of(60, ["C"]) == "D"
