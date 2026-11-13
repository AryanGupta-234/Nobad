"""Network Intelligence analysis: DNS comparison (dnsintel), layer attribution (investigate), the smart fix agent,
adapter discovery parsing (system) and local history. No real network and no Windows commands: the lowest layer
(DNS wire queries, TCP/TLS/HTTP probes, the PowerShell runner, captive check, ping) is replaced by recording fakes."""
import copy
import json
import re
import socket
import threading
import types
import urllib.request

import pytest

from nobadvpn import netinfo, netjournal
from nobadvpn.netintel import agent, dnsintel, dnswire, history, investigate, probes, system

TARGET = "blockedsite.com"
REAL = ["104.21.40.212", "172.67.188.97"]          # what 1.1.1.1 and 8.8.8.8 return
RPZ_CNAME = "restricted.rpz.airtelspam.com"
RPZ_IP = "13.127.247.216"
NET_DNS = "192.168.1.1"
SETTINGS = {"ni_reference_dns": "1.1.1.1, 8.8.8.8, 2606:4700:4700::1111", "ni_history": True, "ni_autofix": False}
_RCODES = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}


# ====================================================================== guards: nothing real may run
@pytest.fixture(autouse=True)
def no_real_io(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError(f"real network / system access attempted: {a[:2]}")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    for mod in (agent, system, netjournal):
        monkeypatch.setattr(mod, "run", boom)
    monkeypatch.setattr(agent, "ping_stats", boom)
    monkeypatch.setattr(netinfo, "captive_check", boom)
    # history / journal / fix profiles in a per-test folder
    monkeypatch.setattr(history, "NI_DIR", str(tmp_path / "netintel"))
    monkeypatch.setattr(agent, "PROFILES", str(tmp_path / "netintel" / "fix_profiles.json"))
    monkeypatch.setattr(netjournal, "JOURNAL_PATH", str(tmp_path / "netchanges.json"))


# ====================================================================== fake DNS
def rr(name, rtype, data, ttl=300):
    return {"name": name, "type": rtype, "ttl": ttl, "data": data}


def dns_result(server, name, rtype, answers=(), rcode=0, error=None, rtt=12.0):
    """Same shape as dnswire._result()."""
    return {"server": server, "transport": "udp", "name": name, "type": rtype,
            "rcode": None if error else rcode, "rcode_name": None if error else _RCODES[rcode],
            "flags": {}, "answers": [] if error else list(answers), "authority": [], "additional": [],
            "rtt_ms": rtt, "error": error}


def site(v4=(), cname=None, v6=()):
    """Resolver behaviour: answer A/AAAA (optionally through a CNAME); everything else NOERROR/empty."""
    def fn(name, rtype):
        ips = v4 if rtype == "A" else v6 if rtype == "AAAA" else None
        if ips is None:
            return [], 0, None
        owner = cname or name
        ans = ([rr(name, "CNAME", cname)] if cname else []) + [rr(owner, rtype, ip) for ip in ips]
        return ans, 0, None
    return fn


def nxdomain(name, rtype):
    return [], 3, None


def servfail(name, rtype):
    return [], 2, None


def timeout(name, rtype):
    return [], 0, "timeout"


class FakeDNS:
    """Replaces dnswire.query: behaviour per resolver IP. Thread safe (resolve_matrix runs queries in parallel)."""

    def __init__(self, by_server, default=timeout):
        self.by_server, self.default = by_server, default
        self.calls, self._lock = [], threading.Lock()

    def __call__(self, name, rtype="A", server="1.1.1.1", port=53, timeout=2.0, **kw):
        with self._lock:
            self.calls.append((server, name, rtype))
        n = name.lower().rstrip(".")
        ans, rcode, err = self.by_server.get(server, self.default)(n, rtype)
        return dns_result(server, n, rtype, ans, rcode, err)


def install_dns(monkeypatch, by_server, default=timeout):
    fake = FakeDNS(by_server, default)
    monkeypatch.setattr(dnswire, "query", fake)
    monkeypatch.setattr(dnswire, "query_doh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected DoH")))
    return fake


NET = {"ip": NET_DNS, "label": f"Network DNS {NET_DNS}", "group": "network", "via": "dhcp", "in_use": True}
REFS = [{"ip": "1.1.1.1", "label": "Independent 1.1.1.1", "group": "reference", "via": "direct", "in_use": False},
        {"ip": "8.8.8.8", "label": "Independent 8.8.8.8", "group": "reference", "via": "direct", "in_use": False}]


def matrix_for(monkeypatch, network_fn, ref_fns=None, name=TARGET):
    ref_fns = ref_fns or [site(REAL), site(REAL)]
    install_dns(monkeypatch, {NET_DNS: network_fn, **{r["ip"]: f for r, f in zip(REFS, ref_fns)}})
    return dnsintel.resolve_matrix(name, [NET] + REFS)


def kinds(findings):
    return [f["kind"] for f in findings]


# ====================================================================== dnsintel: helpers
@pytest.mark.parametrize("name,reg", [("a.b.example.co.uk", "example.co.uk"), ("restricted.rpz.airtelspam.com", "airtelspam.com"),
                                      ("block.example-isp.net", "example-isp.net"), ("Example.COM.", "example.com"), ("", "")])
def test_registrable(name, reg):
    assert dnsintel.registrable(name) == reg


def test_policy_words_are_generic_tokens():
    assert dnsintel.policy_words_in(RPZ_CNAME) == ["restricted", "rpz"]
    assert dnsintel.policy_words_in("block.example-isp.net") == ["block"]
    assert dnsintel.policy_words_in("sinkhole-01.provider.example") == ["sinkhole"]
    assert dnsintel.policy_words_in("cdn.cloudflare.net") == []
    assert dnsintel.policy_words_in("blockchain.example") == []     # substring of a word is not a policy word


def test_chain_of_follows_cnames_from_the_question():
    res = {"answers": [rr("www.x.com", "CNAME", "edge.cdn.net", 60), rr("edge.cdn.net", "CNAME", "e1.cdn.net", 30),
                       rr("e1.cdn.net", "A", "203.0.113.7", 20), rr("e1.cdn.net", "A", "203.0.113.5", 20)]}
    assert dnsintel.chain_of("WWW.x.com.", res) == {"cnames": ["edge.cdn.net", "e1.cdn.net"],
                                                     "addrs": ["203.0.113.5", "203.0.113.7"], "min_ttl": 20}
    assert dnsintel.chain_of("x.com", {"answers": []}) == {"cnames": [], "addrs": [], "min_ttl": None}


def test_resolve_matrix_keeps_resolver_order_and_summarises(monkeypatch):
    m = matrix_for(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME))
    assert [r["ip"] for r in m] == [NET_DNS, "1.1.1.1", "8.8.8.8"]
    a = m[0]["results"]["A"]
    assert a["rcode"] == "NOERROR" and a["cnames"] == [RPZ_CNAME] and a["addrs"] == [RPZ_IP] and a["error"] is None
    assert set(m[1]["results"]) == {"A", "AAAA"} and m[1]["results"]["A"]["addrs"] == sorted(REAL)


# ====================================================================== dnsintel: analysis
def test_reference_scenario_rpz_redirect_is_dns_filtering_with_medium_confidence(monkeypatch):
    m = matrix_for(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME))
    out = dnsintel.analyze(TARGET, m)
    assert out["consensus"]["addrs"] == sorted(REAL) and out["consensus"]["agree"] and out["consensus"]["answered"] == 2
    assert kinds(out["findings"]) == ["dns-filtering"]          # only the network resolver is judged
    f = out["findings"][0]
    assert f["resolver"]["ip"] == NET_DNS and f["layer"] == "dns"
    assert f["redirect"] == [RPZ_CNAME] and f["filtered_ips"] == [RPZ_IP]
    ev = " | ".join(f["evidence"])
    assert "RPZ-style naming" in ev and RPZ_CNAME in ev and "different domain" in ev
    assert "none of" in ev and RPZ_IP in ev
    # several independent signals, but DNS answers alone are not "high certainty"
    assert 0.55 <= f["confidence"] < 0.8 and f["confidence_label"] == "medium" and f["severity"] == "bad"


def test_generalises_to_any_isp_name_and_private_sinkhole(monkeypatch):
    m = matrix_for(monkeypatch, site(["10.10.10.10"], cname="block.example-isp.net"), name="news.example.org")
    f, = dnsintel.analyze("news.example.org", m)["findings"]
    assert f["kind"] == "dns-filtering" and f["redirect"] == ["block.example-isp.net"] and f["filtered_ips"] == ["10.10.10.10"]
    ev = " | ".join(f["evidence"])
    assert "policy words: block" in ev and "non-public address(es) 10.10.10.10" in ev
    assert "RPZ" not in ev and "airtel" not in ev.lower()
    assert 0.55 <= f["confidence"] < 0.99


def test_single_signal_is_only_a_low_confidence_divergence(monkeypatch):
    # different public address, no redirect, no policy words: geo-DNS / CDN does this all the time
    m = matrix_for(monkeypatch, site(["93.184.216.34"]))
    f, = dnsintel.analyze(TARGET, m)["findings"]
    assert f["kind"] == "dns-divergence" and f["confidence"] == 0.15 and f["confidence_label"] == "low"
    assert f["severity"] == "warn"


def test_agreeing_resolvers_produce_no_finding(monkeypatch):
    m = matrix_for(monkeypatch, site(REAL))
    out = dnsintel.analyze(TARGET, m)
    assert out["findings"] == [] and out["consensus"]["agree"]


def test_same_site_cname_with_shared_address_is_not_filtering(monkeypatch):
    # www -> cdn.<same domain>, one shared address: a contradiction outweighs a lone mismatch
    m = matrix_for(monkeypatch, site([REAL[0], "104.21.40.99"], cname="edge.blockedsite.com"))
    assert dnsintel.analyze(TARGET, m)["findings"] == []


def test_contradiction_lowers_confidence(monkeypatch):
    m = matrix_for(monkeypatch, site([REAL[0], RPZ_IP], cname=RPZ_CNAME))
    f, = dnsintel.analyze(TARGET, m)["findings"]
    assert any("shares at least one address" in c for c in f["contra"])
    pure, = dnsintel.analyze(TARGET, matrix_for(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME)))["findings"]
    assert f["confidence"] < pure["confidence"]


def test_known_sinkhole_and_certificate_evidence_raise_confidence(monkeypatch):
    m = matrix_for(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME))
    base = dnsintel.analyze(TARGET, m)["findings"][0]["confidence"]
    hist = dnsintel.analyze(TARGET, m, history_sinkholes=[RPZ_IP])["findings"][0]
    assert hist["confidence"] > base and any("already seen" in e for e in hist["evidence"])
    tls_ev = {"suspect": {RPZ_IP: {"verify_ok": False, "names": ["*.airtelspam.com"]}},
              "consensus": {ip: {"verify_ok": True} for ip in REAL}}
    tls = dnsintel.analyze(TARGET, m, tls_evidence=tls_ev)["findings"][0]
    assert tls["confidence"] >= 0.8 and tls["confidence_label"] == "high"
    assert any("do not present a valid certificate" in e and "*.airtelspam.com" in e for e in tls["evidence"])
    # the suspect address serving a VALID certificate contradicts filtering
    ok_ev = {"suspect": {RPZ_IP: {"verify_ok": True}}, "consensus": {ip: {"verify_ok": True} for ip in REAL}}
    assert dnsintel.analyze(TARGET, m, tls_evidence=ok_ev)["findings"][0]["confidence"] < base


def test_nxdomain_from_network_while_references_answer(monkeypatch):
    f, = dnsintel.analyze(TARGET, matrix_for(monkeypatch, nxdomain))["findings"]
    assert f["kind"] == "dns-filtering" and f["confidence"] == 0.45 and f["severity"] == "warn"
    assert "NXDOMAIN" in f["evidence"][0]


def test_network_resolver_timeout_is_a_failure_not_filtering(monkeypatch):
    out = dnsintel.analyze(TARGET, matrix_for(monkeypatch, timeout))
    assert kinds(out["findings"]) == ["resolver-failed"]
    f = out["findings"][0]
    assert f["confidence"] == 0.7 and "not filtering" in f["recommend"][0] and "timeout" in f["evidence"][0]
    assert "filtered_ips" not in f


def test_network_resolver_servfail_is_a_resolver_error(monkeypatch):
    assert kinds(dnsintel.analyze(TARGET, matrix_for(monkeypatch, servfail))["findings"]) == ["resolver-error"]


def test_one_reference_timing_out_still_allows_comparison(monkeypatch):
    m = matrix_for(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME), [timeout, site(REAL)])
    out = dnsintel.analyze(TARGET, m)
    assert out["consensus"]["answered"] == 1 and kinds(out["findings"]) == ["dns-filtering"]


def test_all_references_unreachable_gives_no_filtering_verdict(monkeypatch):
    out = dnsintel.analyze(TARGET, matrix_for(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME), [timeout, timeout]))
    assert kinds(out["findings"]) == ["references-unreachable"]


def test_name_that_does_not_exist_anywhere(monkeypatch):
    out = dnsintel.analyze(TARGET, matrix_for(monkeypatch, nxdomain, [nxdomain, nxdomain]))
    assert kinds(out["findings"]) == ["name-does-not-exist"] and out["findings"][0]["severity"] == "info"


def test_consensus_detects_disagreeing_references(monkeypatch):
    m = matrix_for(monkeypatch, site(REAL), [site(["198.18.0.1"]), site(["198.18.0.2"])])
    c = dnsintel.consensus(m)
    assert c["agree"] is False and c["addrs"] == {"198.18.0.1", "198.18.0.2"}
    f, = dnsintel.analyze(TARGET, m)["findings"]
    assert f["confidence"] == 0.07          # a mismatch counts for less when the references disagree among themselves


# ====================================================================== system: discovery parsing
# What the module's PowerShell script prints (ConvertTo-Json -Compress), for a laptop on home Wi-Fi with the NOBAD
# tunnel "Home" up, an unplugged Ethernet port, a Hyper-V switch, and a second (higher-metric) wired uplink.
def _raw(**wifi_over):
    wifi = {"index": 12, "name": "Wi-Fi", "desc": "Intel(R) Wi-Fi 6 AX201 160MHz", "status": "Up", "media": "Native 802.11",
            "phys": "Native 802.11", "speed": "866.7 Mbps", "virtual": False, "hw": True,
            "v4": [{"ip": "192.168.1.5", "prefix": 24, "origin": "Dhcp"}],
            "v6": [{"ip": "fe80::1c2b:3d4e:5f60:7182%12", "prefix": 64, "origin": "WellKnown", "suffix": "Link"}],
            "gw4": [{"nh": "192.168.1.1", "metric": 0}], "gw6": [],
            "dns4": ["192.168.1.1"], "dns6": [], "suffix": "",
            "dhcpdns": "192.168.1.1", "staticdns": "", "dhcpdomain": "",
            "metric4": 35, "metric6": 35, "dhcp4": "Enabled", "mtu": 1500,
            "profile": {"name": "HomeNet", "category": "Private", "c4": "Internet", "c6": "NoTraffic"}}
    wifi.update(wifi_over)
    return {"adapters": [
        wifi,
        {"index": 7, "name": "Ethernet", "desc": "Realtek PCIe GbE Family Controller", "status": "Disconnected",
         "media": "802.3", "phys": "802.3", "speed": "0 bps", "virtual": False, "hw": True, "v4": [], "v6": [],
         "gw4": [], "gw6": [], "dns4": [], "dns6": [], "suffix": "", "dhcpdns": "", "staticdns": "", "dhcpdomain": "",
         "metric4": 5, "metric6": 5, "dhcp4": "Enabled", "mtu": 1500, "profile": None},
        {"index": 19, "name": "Ethernet 2", "desc": "USB 10/100/1000 LAN", "status": "Up", "media": "802.3", "phys": "802.3",
         "speed": "1 Gbps", "virtual": False, "hw": True, "v4": [{"ip": "100.72.4.9", "prefix": 10, "origin": "Dhcp"}],
         "v6": [], "gw4": [{"nh": "100.64.0.1", "metric": 256}], "gw6": [], "dns4": ["100.64.0.1"], "dns6": [],
         "suffix": "", "dhcpdns": "100.64.0.1", "staticdns": "", "dhcpdomain": "", "metric4": 45, "metric6": 45,
         "dhcp4": "Enabled", "mtu": 1500, "profile": None},
        {"index": 31, "name": "Home", "desc": "WireGuard Tunnel", "status": "Up", "media": "", "phys": "Unspecified",
         "speed": "100 Gbps", "virtual": False, "hw": False, "v4": [{"ip": "10.2.0.2", "prefix": 32, "origin": "Manual"}],
         "v6": [], "gw4": [{"nh": "0.0.0.0", "metric": 0}], "gw6": [], "dns4": ["10.2.0.1"], "dns6": [], "suffix": "",
         "dhcpdns": "", "staticdns": "10.2.0.1", "dhcpdomain": "", "metric4": 5, "metric6": 5, "dhcp4": "Disabled",
         "mtu": 1420, "profile": None},
        {"index": 44, "name": "vEthernet (Default Switch)", "desc": "Hyper-V Virtual Ethernet Adapter", "status": "Up",
         "media": "802.3", "phys": "Unspecified", "speed": "10 Gbps", "virtual": True, "hw": False,
         "v4": [{"ip": "172.20.48.1", "prefix": 20, "origin": "Manual"}], "v6": [], "gw4": [], "gw6": [],
         "dns4": [], "dns6": [], "suffix": "", "dhcpdns": "", "staticdns": "", "dhcpdomain": "",
         "metric4": 5000, "metric6": 5000, "dhcp4": "Disabled", "mtu": 1500, "profile": None},
    ], "doh": [{"server": "1.1.1.1", "template": "https://cloudflare-dns.com/dns-query", "auto": False},
               {"server": "8.8.8.8", "template": "https://dns.google/dns-query", "auto": False},
               {"server": None, "template": "https://x.invalid/dns-query", "auto": False}],
        "domain_joined": False, "nrpt": 0}


def home_snap(**wifi_over):
    """Wi-Fi only (no tunnel): the network every investigate/agent test runs on."""
    raw = _raw(**wifi_over)
    raw["adapters"] = [raw["adapters"][0]]
    raw["doh"] = []
    return system.parse_snapshot(json.loads(json.dumps(raw)))


def test_parse_snapshot_roles_primary_tunnel_and_routes():
    s = system.parse_snapshot(json.loads(json.dumps(_raw())), tunnel_name="Home")
    by = {a["name"]: a for a in s["adapters"]}
    assert [by[n]["role"] for n in ("Wi-Fi", "Ethernet", "Home", "vEthernet (Default Switch)")] == \
        ["physical", "physical", "nobad-tunnel", "virtual"]
    assert s["primary"] == 12            # lowest route+interface metric among real uplinks; the tunnel never counts
    assert s["tunnel"] == 31 and s["v4_available"] and not s["v6_available"]
    w = by["Wi-Fi"]
    assert w["gateways4"] == ["192.168.1.1"] and w["default4"] and w["route_metric4"] == 0 and w["dhcp4"]
    assert w["ipv4"] == [{"ip": "192.168.1.5", "prefix": 24, "origin": "Dhcp", "kind": "private"}]
    assert w["ipv6"][0]["kind"] == "link-local" and w["global_v6"] == []
    assert by["Home"]["default4"] and by["Home"]["gateways4"] == []        # on-link 0.0.0.0 next hop
    assert by["Ethernet 2"]["ipv4"][0]["kind"] == "cgnat" and by["Ethernet 2"]["route_metric4"] == 256
    assert not by["Ethernet"]["default4"] and by["Ethernet"]["route_metric4"] is None
    assert s["doh_templates"] == [{"server": "1.1.1.1", "template": "https://cloudflare-dns.com/dns-query", "auto": False},
                                  {"server": "8.8.8.8", "template": "https://dns.google/dns-query", "auto": False}]
    # without the engine's tunnel name the WireGuard adapter is just a virtual adapter
    assert system.adapter(system.parse_snapshot(_raw()), 31)["role"] == "virtual"


def test_parse_snapshot_single_objects_ipv6_and_dns_strings():
    # ConvertTo-Json emits a single object (not a list) when there is only one; registry DNS strings use , or space
    wifi = _raw()["adapters"][0]
    wifi.update(v6={"ip": "2401:4900:1c2a:5e3:a1b2:c3d4:e5f6:789", "prefix": 64, "origin": "RouterAdvertisement"},
                gw6={"nh": "fe80::1", "metric": 0}, dns4="192.168.1.1", dhcpdns="192.168.1.1 192.168.1.2",
                staticdns="1.1.1.1,8.8.8.8", suffix="corp.example", dhcpdomain="corp.example")
    s = system.parse_snapshot({"adapters": wifi, "doh": None, "domain_joined": True, "nrpt": 2})
    a = s["adapters"][0]
    assert a["global_v6"] == ["2401:4900:1c2a:5e3:a1b2:c3d4:e5f6:789"] and a["gateways6"] == ["fe80::1"]
    assert s["v6_available"] and s["primary"] == 12 and s["tunnel"] is None
    assert a["dns4"] == ["192.168.1.1"] and a["dhcp_dns"] == ["192.168.1.1", "192.168.1.2"]
    assert a["static_dns"] == ["1.1.1.1", "8.8.8.8"] and a["suffix"] == "corp.example"
    assert s["domain_joined"] and s["nrpt_rules"] == 2 and s["doh_templates"] == []


def test_resolvers_from_snapshot():
    s = system.parse_snapshot(_raw(dns6=["fe80::1%12"], dhcpdns="192.168.1.1"), tunnel_name="Home")
    assert [(r["ip"], r["via"]) for r in system.system_resolvers(s)] == [("10.2.0.1", "tunnel"), ("192.168.1.1", "uplink")]
    assert [r["ip"] for r in system.network_resolvers(s)] == ["192.168.1.1"]
    sig = system.signature(s)
    assert sig == {"gateways4": ["192.168.1.1"], "dns": ["192.168.1.1", "fe80::1%12"], "media": "Native 802.11",
                   "v6": False, "suffix": "", "tunnel": True}


def test_offline_snapshot_has_no_primary():
    raw = _raw(gw4=[], status="Disconnected")
    raw["adapters"] = raw["adapters"][:2]
    s = system.parse_snapshot(raw)
    assert s["primary"] is None and not s["v4_available"] and system.network_resolvers(s) == []


def test_snapshot_runs_one_powershell_and_handles_garbage(monkeypatch):
    monkeypatch.setattr(system, "os", types.SimpleNamespace(name="nt"))
    calls = []

    def runner(out):
        def r(cmd, timeout=15):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout=out, stderr="WARNING: x")
        return r
    s = system.snapshot("Home", runner=runner(json.dumps(_raw())))
    assert s["tunnel"] == 31 and calls[0][0] == "powershell" and "Get-NetAdapter" in calls[0][-1]
    bad = system.snapshot(None, runner=runner("Get-NetAdapter : Access denied"))
    assert bad["error"] == "could not read the network configuration" and bad["detail"] == "WARNING: x"
    monkeypatch.setattr(system, "os", types.SimpleNamespace(name="posix"))
    assert "error" in system.snapshot(None, runner=runner("{}")) and len(calls) == 2


def test_windows_fec0_placeholder_dns_is_not_a_resolver():
    s = home_snap(dns6=["fec0:0:0:ffff::1%1", "fec0:0:0:ffff::2%1", "fec0:0:0:ffff::3%1"])
    assert [r["ip"] for r in system.system_resolvers(s)] == ["192.168.1.1"]


def test_resolver_set_groups_and_references(monkeypatch):
    raw = _raw(dns4=["1.1.1.1"], staticdns="1.1.1.1")
    raw["adapters"] = raw["adapters"][:1]
    s = system.parse_snapshot(raw)
    rows = investigate.resolver_set(s, SETTINGS)
    assert [(r.get("ip") or r.get("doh"), r["group"]) for r in rows] == [
        ("192.168.1.1", "network"), ("1.1.1.1", "configured"), ("8.8.8.8", "reference"),   # 1.1.1.1 not repeated
        ("https://cloudflare-dns.com/dns-query", "encrypted"), ("https://dns.google/dns-query", "encrypted")]
    assert rows[0]["in_use"] is False and rows[1]["in_use"] is True       # Windows uses 1.1.1.1, not the router
    assert all(r.get("ip") != "2606:4700:4700::1111" for r in rows)      # no IPv6 path: no IPv6 references
    assert investigate.reference_ips({"ni_reference_dns": "1.1.1.1; bogus, 1.1.1.1 ,::1"}) == ["1.1.1.1", "::1"]


@pytest.mark.parametrize("raw,want", [("https://Example.com:8443/path?q=1", "example.com"), ("WWW.example.org.", "www.example.org"),
                                      ("bücher.de", "xn--bcher-kva.de")])
def test_normalize_target(raw, want):
    assert investigate.normalize_target(raw) == want


@pytest.mark.parametrize("raw", ["1.2.3.4", "[2001:db8::1]", "not a name", "", "localhost"])
def test_normalize_target_rejects(raw):
    with pytest.raises(ValueError):
        investigate.normalize_target(raw)


# ====================================================================== history
def sig(**over):
    s = {"gateways4": ["192.168.1.1"], "dns": ["192.168.1.1"], "media": "Native 802.11", "v6": False, "suffix": "", "tunnel": False}
    s.update(over)
    return s


def test_network_key_is_stable_and_private():
    a, b = home_snap(), home_snap(dns4=["9.9.9.9"])
    assert history.network_key(a) == history.network_key(b)              # manual DNS change: same network
    other = home_snap(gw4=[{"nh": "10.0.0.1", "metric": 0}])
    assert history.network_key(other) != history.network_key(a)
    assert re.fullmatch(r"[0-9a-f]{16}", history.network_key(a)) and "192.168" not in history.network_key(a)
    assert history.network_key({"adapters": [], "primary": None}) == "offline"


def test_baseline_created_then_seen_n_times():
    first = history.compare_and_learn("net1", sig(), 20.0)
    assert first["known"] is False and first["seen"] == 1 and first["changes"] == []
    for n in (2, 3):
        r = history.compare_and_learn("net1", sig(), 22.0)
        assert r["known"] and r["seen"] == n and r["changes"] == [] and r["first"] == first["first"]
    b = history.baseline("net1")
    assert b["seen"] == 3 and 20.0 < b["dns_ms"] < 22.0                  # moving average
    assert history.compare_and_learn("net2", sig(), None)["seen"] == 1  # networks are independent


def test_baseline_detects_changed_network():
    history.compare_and_learn("net1", sig(), 20.0)
    r = history.compare_and_learn("net1", sig(dns=["203.0.113.66"], gateways4=["192.168.1.254"], v6=True), 200.0)
    by = {c["what"]: c for c in r["changes"]}
    assert set(by) == {"gateway", "DNS servers", "IPv6", "DNS latency"}
    assert by["DNS servers"] == {"what": "DNS servers", "before": ["192.168.1.1"], "now": ["203.0.113.66"]}
    assert by["IPv6"]["before"] == "unavailable" and by["IPv6"]["now"] == "available"
    # the new state becomes the baseline
    assert history.compare_and_learn("net1", sig(dns=["203.0.113.66"], gateways4=["192.168.1.254"], v6=True), 50.0)["changes"] == []


def test_history_disabled_writes_nothing(tmp_path):
    r = history.compare_and_learn("net1", sig(), 20.0, enabled=False)
    assert r["seen"] == 1 and history.baseline("net1") is None
    history.append("investigation", {"target": "x"}, enabled=False)
    history.note_filtered("net1", "x.com", [RPZ_IP], enabled=False)
    assert history.recent() == [] and history.sinkholes("net1") == {}


def test_history_lines_sinkholes_and_clear(monkeypatch):
    monkeypatch.setattr(history, "MAX_LINES", 3)
    for i in range(5):
        history.append("investigation", {"target": f"s{i}.com"})
    history.append("overview", {"network": "net1"})
    assert [d.get("target") for d in history.recent(kind="investigation")] == ["s4.com", "s3.com"]
    assert len(history.recent()) == 3 and history.recent(limit=1)[0]["kind"] == "overview"
    history.note_filtered("net1", "a.com", [RPZ_IP])
    history.note_filtered("net1", "b.com", [RPZ_IP, "10.10.10.10"])
    history.note_filtered("net1", "a.com", [RPZ_IP])
    assert history.sinkholes("net1") == {RPZ_IP: ["a.com", "b.com"], "10.10.10.10": ["b.com"]}
    assert history.sinkholes("net2") == {}
    history.compare_and_learn("net1", sig(), 10.0)
    history.clear()
    assert history.recent() == [] and history.sinkholes("net1") == {} and history.baseline("net1") is None
    history.clear()                                                    # nothing left: still fine


# ====================================================================== investigate: layer attribution
def tls_valid(ip, sni):
    return {"ip": ip, "sni": sni, "port": 443, "tcp_ok": True, "tls_ok": True, "verify_ok": True, "names": [sni]}


def tls_wrong_cert(ip, sni):
    return {"ip": ip, "sni": sni, "port": 443, "tcp_ok": True, "tls_ok": True, "verify_ok": False,
            "error": "cert-mismatch", "names": ["*.sinkhole.example"]}


class FakeProbes:
    def __init__(self, tcp=lambda ip, port: True, tls=None, os_ips=None, http_status=200, intercepted=False):
        self.tcp, self.os_ips, self.http_status, self.intercepted = tcp, os_ips, http_status, intercepted
        self.tls = tls or (lambda ip, sni: tls_valid(ip, sni) if ip in REAL else tls_wrong_cert(ip, sni))
        self.calls, self._lock = [], threading.Lock()

    def _rec(self, *c):
        with self._lock:
            self.calls.append(c)

    def tcp_connect(self, ip, port=443, timeout=3.0):
        self._rec("tcp", ip, port)
        return {"ip": ip, "port": port, "ok": True, "rtt_ms": 9.0} if self.tcp(ip, port) else \
            {"ip": ip, "port": port, "ok": False, "error": "timeout", "elapsed_ms": 3000.0}

    def tls_probe(self, ip, sni, port=443, timeout=4.0):
        self._rec("tls", ip, sni)
        return self.tls(ip, sni)

    def http_probe(self, ip, host, tls=True, path="/", timeout=5.0):
        self._rec("http", ip, host)
        return {"ip": ip, "host": host, "tls": tls, "ok": True, "status": self.http_status, "title": "Site"}

    def os_resolve(self, name, timeout=5.0):
        self._rec("os", name)
        return {"ok": True, "ips": list(self.os_ips), "ms": 3.0} if self.os_ips else {"ok": False, "error": "no such name"}

    def interception_test(self, v6=False, name="example.com", timeout=1.5):
        self._rec("intercept", v6)
        p = [{"target": "192.0.2.53", "answered": self.intercepted, "rcode": "NOERROR" if self.intercepted else None,
              "answers": ["192.168.1.1"] if self.intercepted else [], "error": None if self.intercepted else "timeout"}]
        return {"intercepted": self.intercepted, "probes": p}

    def install(self, monkeypatch):
        for n in ("tcp_connect", "tls_probe", "http_probe", "os_resolve", "interception_test"):
            monkeypatch.setattr(probes, n, getattr(self, n))   # probes.sni_filter_check stays real
        return self


def run_site(monkeypatch, network_fn, fp, snap=None, settings=SETTINGS, **kw):
    install_dns(monkeypatch, {NET_DNS: network_fn, "1.1.1.1": site(REAL), "8.8.8.8": site(REAL)})
    fp.install(monkeypatch)
    return investigate.investigate_site(TARGET, settings, snap=snap or home_snap(), **kw)


def rec_ids(res):
    return [r["id"] for r in res["recommendations"]]


def test_investigate_healthy_site(monkeypatch):
    res = run_site(monkeypatch, site(REAL), FakeProbes(os_ips=REAL))
    assert res["ok"] and res["verdict"] == "ok" and res["affected"] is False
    assert [f for f in res["findings"] if f["severity"] in ("bad", "warn")] == [] and res["recommendations"] == []
    assert res["data"]["consensus"]["addrs"] == sorted(REAL)
    assert history.recent(kind="investigation")[0]["verdict"] == "ok"


def test_investigate_dns_cause_when_real_ip_works(monkeypatch):
    fp = FakeProbes(os_ips=[RPZ_IP])
    res = run_site(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME), fp)
    assert res["verdict"] == "dns-filtering" and res["affected"] is True
    assert kinds(res["findings"]) == ["dns-filtering"]                    # nothing on TCP/TLS/HTTP
    f = res["findings"][0]
    assert f["in_use"] is True and f["confidence"] >= 0.8                # + certificate evidence from the sinkhole
    assert ("tls", RPZ_IP, TARGET) in fp.calls and ("tcp", REAL[0], 443) in fp.calls
    assert ("http", sorted(REAL)[0], TARGET) in fp.calls                   # real site was reached and served normally
    recs = {r["id"]: r for r in res["recommendations"]}
    assert recs["vpn"]["action"] == "vpn" and recs["dns"]["action"] == "dns_fix" and "more" in recs
    assert "doh" not in recs
    # the sinkhole is remembered for this network and strengthens the next investigation
    assert history.sinkholes(res["network_key"]) == {RPZ_IP: [TARGET]}


def test_investigate_dns_filtering_with_interception_recommends_doh_not_dns_change(monkeypatch):
    res = run_site(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME), FakeProbes(os_ips=[RPZ_IP], intercepted=True))
    assert res["verdict"] == "dns-interception"
    assert "dns-filtering" in kinds(res["findings"]) and rec_ids(res)[0] == "vpn"
    assert all(r.get("action") != "dns_fix" for r in res["recommendations"])


def test_investigate_windows_already_uses_good_resolver(monkeypatch):
    snap = home_snap(dns4=["1.1.1.1"], staticdns="1.1.1.1")              # router filters, Windows asks 1.1.1.1
    res = run_site(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME), FakeProbes(os_ips=REAL), snap=snap)
    assert res["verdict"] == "dns-filtering" and res["affected"] is False
    f = next(f for f in res["findings"] if f["kind"] == "dns-filtering")
    assert f["in_use"] is False and "Other devices on this network" in f["note"]
    assert rec_ids(res)[0] == "none"
    assert agent.preflight(res, snap, manual=True)[0] is False


def test_investigate_sni_block_when_tcp_works(monkeypatch):
    def tls(ip, sni):      # real name: reset after ClientHello; neutral name: server answers with an alert
        if sni == TARGET:
            return {"ip": ip, "sni": sni, "port": 443, "tcp_ok": True, "tls_ok": False, "verify_ok": False, "error": "reset"}
        return {"ip": ip, "sni": sni, "port": 443, "tcp_ok": True, "tls_ok": False, "verify_ok": False, "error": "tls-error"}
    fp = FakeProbes(os_ips=REAL, tls=tls)
    res = run_site(monkeypatch, site(REAL), fp)
    assert res["verdict"] == "sni-filtering" and kinds(res["findings"]) == ["sni-filtering"]
    f = res["findings"][0]
    assert f["layer"] == "tls" and f["confidence"] == 0.8 and "reset" in f["evidence"][0]
    assert ("tls", sorted(REAL)[0], "nobad-sni-control.invalid") in fp.calls     # control handshake really made
    first = res["recommendations"][0]
    assert first["id"] == "vpn" and first["action"] == "vpn" and "DNS change won't help" in first["text"]
    assert all(r.get("action") != "dns_fix" for r in res["recommendations"])


def test_investigate_tls_failure_without_sni_evidence(monkeypatch):
    def tls(ip, sni):      # both names cut off: not SNI-specific
        return {"ip": ip, "sni": sni, "port": 443, "tcp_ok": True, "tls_ok": False, "verify_ok": False, "error": "reset"}
    res = run_site(monkeypatch, site(REAL), FakeProbes(os_ips=REAL, tls=tls))
    assert res["verdict"] == "tls-failed" and kinds(res["findings"]) == ["tls-failed"]


def test_investigate_transport_failure_to_every_address(monkeypatch):
    fp = FakeProbes(os_ips=REAL, tcp=lambda ip, port: False)
    res = run_site(monkeypatch, site(REAL), fp)
    assert res["verdict"] == "ip-unreachable" and kinds(res["findings"]) == ["ip-unreachable"]
    f = res["findings"][0]
    assert f["layer"] == "tcp" and f["confidence"] == 0.7                # port 80 also closed
    assert {c[1:] for c in fp.calls if c[0] == "tcp"} == {(ip, p) for ip in REAL for p in (443, 80)}
    assert "This is not a DNS problem: changing DNS won't help." in [r["text"] for r in res["recommendations"]]
    assert res["recommendations"][0]["action"] == "vpn"


def test_investigate_dns_filtered_and_ip_blocked_is_not_a_dns_fix(monkeypatch):
    snap = home_snap()
    res = run_site(monkeypatch, site([RPZ_IP], cname=RPZ_CNAME), FakeProbes(os_ips=[RPZ_IP], tcp=lambda ip, port: ip not in REAL),
                   snap=snap)
    assert res["verdict"] == "ip-unreachable" and {"dns-filtering", "ip-unreachable"} <= set(kinds(res["findings"]))
    assert res["recommendations"][0]["action"] == "vpn"
    ok, why = agent.preflight(res, snap, manual=True)
    assert not ok and any("unreachable" in w for w in why)


def test_investigate_connected_recommends_other_server(monkeypatch):
    tun = types.SimpleNamespace(connected=True, active="Home")
    res = run_site(monkeypatch, site(REAL), FakeProbes(os_ips=REAL, tcp=lambda ip, port: False), tunnel=tun)
    assert rec_ids(res)[0] == "server"


def test_investigate_offline(monkeypatch):
    snap = home_snap(gw4=[])
    fp = FakeProbes()
    install_dns(monkeypatch, {})
    fp.install(monkeypatch)
    res = investigate.investigate_site(TARGET, SETTINGS, snap=snap)
    assert res["verdict"] == "local-network" and kinds(res["findings"]) == ["offline"] and fp.calls == []


def test_investigate_names_the_isp_only_with_evidence(monkeypatch):
    install_dns(monkeypatch, {NET_DNS: site(["10.10.10.10"], cname="block.example-isp.net"),
                              "1.1.1.1": site(REAL), "8.8.8.8": site(REAL)})
    FakeProbes(os_ips=["10.10.10.10"]).install(monkeypatch)
    res = investigate.investigate_site(TARGET, SETTINGS, snap=home_snap(), exit_info={"org": "AS64500 Example ISP Networks"})
    assert res["data"]["isp"]["matches"] == ["example"]
    f = next(f for f in res["findings"] if f["kind"] == "dns-filtering")
    assert "most likely done by your ISP" in f["evidence"][-1] and f["operator"]["provider_known"]
    # no provider information: nothing is claimed
    res2 = investigate.investigate_site(TARGET, SETTINGS, snap=home_snap())
    assert res2["data"]["isp"]["matches"] == [] and res2["data"]["isp"]["note"]


def test_investigate_names_airtel_for_airtelspam_redirect(monkeypatch):
    install_dns(monkeypatch, {NET_DNS: site([RPZ_IP], cname=RPZ_CNAME), "1.1.1.1": site(REAL), "8.8.8.8": site(REAL)})
    FakeProbes(os_ips=[RPZ_IP]).install(monkeypatch)
    res = investigate.investigate_site(TARGET, SETTINGS, snap=home_snap(), exit_info={"org": "AS9498 Bharti Airtel Ltd."})
    assert res["data"]["isp"]["matches"] == ["airtel"]


def test_verdict_priority_and_recommend():
    f = lambda k, sev="bad": {"kind": k, "severity": sev, "recommend": []}
    assert investigate._verdict([f("dns-divergence", "warn"), f("dns-filtering")]) == "dns-filtering"
    assert investigate._verdict([f("dns-filtering"), f("sni-filtering")]) == "sni-filtering"
    assert investigate._verdict([f("name-does-not-exist", "info")]) == "name-does-not-exist"
    assert investigate._verdict([f("multi-uplink", "info")]) == "ok"
    r = investigate.recommend("resolver-failed", [], None, False, None)
    assert r[0]["action"] == "dns_fix"
    r = investigate.recommend("dns-filtering", [], True, False, types.SimpleNamespace(connected=True))
    assert [x["id"] for x in r] == ["dns", "more"]                        # already connected: no "connect" advice


# ====================================================================== investigate: overview (NXDOMAIN hijack)
def overview_dns(network_hijack=True, network_down=False):
    def router(name, rtype):
        if network_down:
            return [], 0, "timeout"
        if name == "" and rtype == "NS":
            return [rr("", "NS", "a.root-servers.net")], 0, None
        if network_hijack and rtype == "A":
            return [rr(name, "A", "92.242.132.24")], 0, None              # invents an answer for a random name
        return [], 3, None

    def ref(name, rtype):
        if name == "" and rtype == "NS":
            return [rr("", "NS", "a.root-servers.net")], 0, None
        return [], 3, None
    return {NET_DNS: router, "1.1.1.1": ref, "8.8.8.8": ref}


def test_overview_detects_nxdomain_hijack_and_learns_baseline(monkeypatch):
    snap = home_snap()
    monkeypatch.setattr(system, "snapshot", lambda tname=None, runner=None: copy.deepcopy(snap))
    dns = install_dns(monkeypatch, overview_dns())
    FakeProbes().install(monkeypatch)
    res = investigate.overview(SETTINGS)
    hj = [f for f in res["findings"] if f["kind"] == "nxdomain-hijack"]
    assert len(hj) == 1 and NET_DNS in hj[0]["title"] and "92.242.132.24" in hj[0]["evidence"][0]
    assert {r["ip"]: r["nx_hijack"] for r in res["resolvers"]} == {NET_DNS: True, "1.1.1.1": False, "8.8.8.8": False}
    assert all(name.endswith((".invalid", ".example.com")) for s, name, t in dns.calls if t == "A")
    assert res["baseline"]["known"] is False and res["baseline"]["seen"] == 1
    assert "changed" not in kinds(res["findings"])
    # same network again, but its DNS server was changed behind the user's back
    snap = home_snap(dns4=["203.0.113.66"], staticdns="203.0.113.66")
    res2 = investigate.overview(SETTINGS)
    ch = [f for f in res2["findings"] if f["kind"] == "changed"]
    assert res2["baseline"]["seen"] == 2 and [c["title"] for c in ch] == ["DNS servers changed since this network was last seen"]
    assert ch[0]["severity"] == "warn" and "hijacked router" in ch[0]["recommend"][0]


def test_overview_honest_resolver_and_down_resolver(monkeypatch):
    snap = home_snap()
    monkeypatch.setattr(system, "snapshot", lambda tname=None, runner=None: copy.deepcopy(snap))
    install_dns(monkeypatch, overview_dns(network_hijack=False))
    FakeProbes().install(monkeypatch)
    assert [f for f in investigate.overview(SETTINGS)["findings"] if f["severity"] != "info"] == []
    install_dns(monkeypatch, overview_dns(network_down=True))
    FakeProbes(intercepted=True).install(monkeypatch)
    res = investigate.overview(SETTINGS)
    down = next(f for f in res["findings"] if f["kind"] == "resolver-down")
    assert down["severity"] == "bad" and "timeout" in down["evidence"][0]           # in use -> bad
    assert "nxdomain-hijack" not in kinds(res["findings"])                         # a timeout is not a hijack
    assert "dns-interception" in kinds(res["findings"])


# ====================================================================== agent: smart fix
CACHE = [{"Entry": "www.bing.com", "Type": 1, "Data": "13.107.21.200"},
         {"Entry": "router.lan", "Type": 1, "Data": "192.168.1.1"},
         {"Entry": TARGET, "Type": 5, "Data": RPZ_CNAME},
         {"Entry": RPZ_CNAME, "Type": 1, "Data": RPZ_IP},
         {"Entry": "github.com", "Type": 1, "Data": "140.82.121.4"}]


def make_inv(conf=0.9, extra_kinds=(), affected=True):
    findings = [{"kind": "dns-filtering", "severity": "bad", "confidence": conf, "title": "filtered"}]
    findings += [{"kind": k, "severity": "bad", "confidence": 0.8, "title": k} for k in extra_kinds]
    row = lambda ip, addrs, rtt: {"ip": ip, "group": "reference", "results": {"A": {"rcode": "NOERROR", "addrs": addrs, "rtt_ms": rtt}}}
    return {"target": TARGET, "verdict": "dns-filtering", "affected": affected, "findings": findings,
            "data": {"consensus": {"addrs": sorted(REAL)},
                     "matrix": [{"ip": NET_DNS, "group": "network", "results": {"A": {"rcode": "NOERROR", "addrs": [RPZ_IP], "rtt_ms": 1}}},
                                row("1.1.1.1", sorted(REAL), 20.0), row("8.8.8.8", sorted(REAL), 10.0),
                                row("9.9.9.9", [RPZ_IP], 5.0),                     # also filtered: never chosen
                                row("2606:4700:4700::1111", [], 4.0)]}}


class FakeWinDNS:
    """PowerShell as seen by netjournal and the agent: one adapter whose DNS can be read and set."""

    def __init__(self, original=("192.168.1.1",), refuse_fix=False, refuse_restore=False, cache=CACHE, unreadable=False):
        self.original = list(original)
        self.current = list(original)
        self.refuse_fix, self.refuse_restore, self.cache, self.unreadable = refuse_fix, refuse_restore, cache, unreadable
        self.scripts, self.sets = [], []

    def __call__(self, cmd, timeout=15, input_text=None):
        assert cmd[0] == "powershell"
        script = cmd[-1]
        self.scripts.append(script)
        out, rc, err = "", 0, ""
        if "Get-NetAdapter -InterfaceIndex" in script:
            rc = 1 if self.unreadable else 0
            out = json.dumps({"alias": "Wi-Fi", "guid": "{6F1C2B3A-0000-4000-8000-00000000AA12}",
                              "v4": " ".join(self.original), "v6": ""})
        elif "Get-DnsClientCache" in script:
            out = json.dumps(self.cache)
        elif "Set-DnsClientServerAddress" in script:
            m = re.search(r"-ServerAddresses @\(([^)]*)\)", script)
            servers = re.findall(r"'([^']+)'", m.group(1)) if m else []
            restoring = servers == self.original or "-ResetServerAddresses" in script
            self.sets.append({"servers": servers, "restore": restoring, "journal": copy.deepcopy(netjournal.entries())})
            if (self.refuse_restore if restoring else self.refuse_fix):
                rc, err = 1, "Set-DnsClientServerAddress : Access is denied."
            else:
                self.current = servers
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


_REAL_RECORD = netjournal.record


def _record_shim(kind, *args, **extra):
    """agent.FixAgent._fix passes the site as target=..., which collides with netjournal.record's positional
    `target` (the adapter) and raises TypeError (see test_fix_with_real_journal_record). The behaviour tests below
    keep the real journal but store the site under 'site', so the rest of the fix logic can still be exercised."""
    if "target" in extra:
        extra["site"] = extra.pop("target")
    return _REAL_RECORD(kind, *args, **extra)


@pytest.fixture
def fixenv(monkeypatch):
    """Installs the fakes; returns a namespace whose fields tests can tweak before calling the agent."""
    env = types.SimpleNamespace(win=FakeWinDNS(), gw_up_after=True, canaries_break=False, site_fixed=True,
                                captive={"status": "open", "portal": None}, snap=home_snap(), resolved=[])

    def os_resolve(name, timeout=5.0):
        env.resolved.append(name)
        changed = env.win.current != env.win.original
        if name == TARGET:
            return {"ok": True, "ips": [REAL[0]] if changed and env.site_fixed else [RPZ_IP]}
        if changed and env.canaries_break:
            return {"ok": False, "error": "no such name"}
        return {"ok": True, "ips": ["203.0.113.10"]}

    def ping(host, count=3, timeout_ms=1500):
        changed = env.win.current != env.win.original
        return {"rtt": 2, "loss": 100 if changed and not env.gw_up_after else 0, "jitter": 0}

    monkeypatch.setattr(netjournal, "run", lambda *a, **k: env.win(*a, **k))
    monkeypatch.setattr(netjournal, "record", _record_shim)
    monkeypatch.setattr(probes, "os_resolve", os_resolve)
    monkeypatch.setattr(agent, "ping_stats", ping)
    monkeypatch.setattr(netinfo, "captive_check", lambda timeout=4: env.captive)
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(time=__import__("time").time, sleep=lambda s: None))
    monkeypatch.setattr(system, "snapshot", lambda tname=None, runner=None: copy.deepcopy(env.snap))
    env.agent = lambda settings=None, **kw: agent.FixAgent(dict(settings or SETTINGS), runner=lambda *a, **k: env.win(*a, **k), **kw)
    return env


def test_plan_picks_independent_resolvers_fastest_first():
    p = agent.plan(make_inv(), home_snap())
    assert p == {"adapter_index": 12, "adapter": "Wi-Fi", "servers": ["8.8.8.8", "1.1.1.1"], "v4": ["8.8.8.8", "1.1.1.1"], "v6": []}


def test_canaries_skip_local_names_and_the_target():
    entries = agent.dns_cache_entries(lambda cmd, timeout=15: types.SimpleNamespace(stdout=json.dumps(CACHE), stderr="", returncode=0))
    assert {"name": TARGET, "type": "CNAME", "data": RPZ_CNAME} in entries
    assert agent.canary_names(entries, exclude=(TARGET,)) == ["www.bing.com", RPZ_CNAME, "github.com"]
    assert agent.canary_names(entries, suffix="bing.com", limit=1) == [RPZ_CNAME]
    one = agent.dns_cache_entries(lambda cmd, timeout=15: types.SimpleNamespace(stdout=json.dumps(CACHE[0]), stderr="", returncode=0))
    assert one == [{"name": "www.bing.com", "type": "A", "data": "13.107.21.200"}]
    assert agent.dns_cache_entries(lambda cmd, timeout=15: types.SimpleNamespace(stdout="oops", stderr="", returncode=1)) == []


@pytest.mark.parametrize("change,reason", [
    (dict(extra_kinds=("sni-filtering",)), "SNI"),
    (dict(extra_kinds=("dns-interception",)), "intercepts plain DNS"),
    (dict(affected=False), "already gets the real address"),
    (dict(conf=0.4), "did not find (confident) DNS filtering"),
])
def test_preflight_refuses_when_a_dns_change_cannot_help(change, reason):
    ok, why = agent.preflight(make_inv(**change), home_snap(), manual=True)
    assert not ok and any(reason in w for w in why)


def test_preflight_environment_refusals_and_auto_threshold():
    assert agent.preflight(make_inv(), home_snap(), manual=True) == (True, [])
    assert agent.preflight(make_inv(conf=0.64), home_snap(), manual=True)[0] is True     # user clicked Fix
    assert agent.preflight(make_inv(conf=0.64), home_snap(), manual=False)[0] is False   # autonomous: needs >= 0.8
    for snap, captive, tunnel, word in (
            (home_snap(suffix="corp.example"), None, None, "local names"),
            (dict(home_snap(), domain_joined=True), None, None, "domain"),
            (dict(home_snap(), nrpt_rules=1), None, None, "NRPT"),
            (home_snap(), {"status": "captive"}, None, "captive portal"),
            (home_snap(), None, types.SimpleNamespace(connected=True), "NOBAD is connected")):
        ok, why = agent.preflight(make_inv(), snap, tunnel, captive, manual=True)
        assert not ok and any(word in w for w in why), word


def test_autonomous_scan_does_nothing_when_switched_off(fixenv, monkeypatch):
    monkeypatch.setattr(system, "snapshot", lambda *a, **k: pytest.fail("snapshot taken while ni_autofix is off"))
    monkeypatch.setattr(investigate, "investigate_site", lambda *a, **k: pytest.fail("investigated while off"))
    a = fixenv.agent(dict(SETTINGS, ni_autofix=False))
    assert a.scan_once() is None
    a.on_network_change()                                # no journal entries, agent off: costs nothing
    assert fixenv.win.scripts == [] and netjournal.entries() == []


def test_autonomous_scan_fixes_when_switched_on(fixenv, monkeypatch):
    seen = []
    monkeypatch.setattr(investigate, "investigate_site", lambda name, *a, **k: seen.append(name) or make_inv())
    a = fixenv.agent(dict(SETTINGS, ni_autofix=True))
    res = a.scan_once()
    assert seen == [TARGET]                              # the CNAME into a policy zone was picked from the DNS cache
    assert res["state"] == "applied" and res["ok"] and fixenv.win.current == ["8.8.8.8", "1.1.1.1"]
    e, = netjournal.entries()
    assert e["auto"] is True and e["reason"].startswith("Auto-fix") and e["state"] == "applied"


def test_autonomous_scan_leaves_medium_confidence_alone(fixenv, monkeypatch):
    monkeypatch.setattr(investigate, "investigate_site", lambda name, *a, **k: make_inv(conf=0.64))
    res = fixenv.agent(dict(SETTINGS, ni_autofix=True)).scan_once()
    assert res["state"] == "refused" and fixenv.win.sets == [] and netjournal.entries() == []


def test_fix_with_real_journal_record(fixenv, monkeypatch):
    monkeypatch.setattr(netjournal, "record", _REAL_RECORD)
    res = fixenv.agent().fix(make_inv(), manual=True, snap=fixenv.snap)
    assert res["state"] == "applied"


def test_fix_journals_original_dns_before_changing_and_verifies(fixenv):
    notes = []
    a = fixenv.agent(notify=lambda *x: notes.append(x))
    res = a.fix(make_inv(), manual=True, snap=fixenv.snap)
    assert res["ok"] and res["state"] == "applied" and res["servers"] == ["8.8.8.8", "1.1.1.1"]
    # the very first change Windows sees already has the undo information on disk
    first = fixenv.win.sets[0]
    assert first["servers"] == ["8.8.8.8", "1.1.1.1"] and not first["restore"]
    j, = first["journal"]
    assert j["state"] == "pending" and j["before"]["static_v4"] == ["192.168.1.1"] and j["before"]["if_index"] == 12
    assert j["after"] == {"servers": ["8.8.8.8", "1.1.1.1"]} and j["network"] == history.network_key(fixenv.snap)
    assert j["target"] == "Wi-Fi" and j["site"] == TARGET
    read = next(i for i, s in enumerate(fixenv.win.scripts) if "Get-NetAdapter -InterfaceIndex 12" in s)
    write = next(i for i, s in enumerate(fixenv.win.scripts) if "Set-DnsClientServerAddress" in s)
    assert read < write
    assert "-InterfaceIndex 12 -ServerAddresses @('8.8.8.8','1.1.1.1')" in fixenv.win.scripts[write]
    # verified: site, every canary, the router
    assert all(c["ok"] for c in res["checks"]) and len(res["checks"]) == 1 + 3 + 1
    assert netjournal.entries()[0]["state"] == "applied" and netjournal.entries()[0]["id"] == res["entry"]
    assert json.load(open(agent.PROFILES))[j["network"]]["servers"] == ["8.8.8.8", "1.1.1.1"]
    assert notes and notes[0][0] == "Site unblocked"
    assert history.recent(kind="fix")[0]["state"] == "applied"


@pytest.mark.parametrize("break_what,reason", [("canaries", "stopped resolving"), ("site", "still does not resolve"),
                                               ("router", "router 192.168.1.1 stopped answering")])
def test_fix_rolls_back_when_verification_fails(fixenv, break_what, reason):
    fixenv.canaries_break = break_what == "canaries"
    fixenv.site_fixed = break_what != "site"
    fixenv.gw_up_after = break_what != "router"
    res = fixenv.agent().fix(make_inv(), manual=True, snap=fixenv.snap)
    assert not res["ok"] and res["state"] == "rolled_back" and any(reason in r for r in res["reasons"])
    assert [s["restore"] for s in fixenv.win.sets] == [False, True]
    assert fixenv.win.current == ["192.168.1.1"]                         # original DNS back
    assert "restored" in res["rollback"] and netjournal.entries() == []
    assert not agent.os.path.exists(agent.PROFILES)


def test_failed_rollback_keeps_the_journal_entry_for_later_reset(fixenv):
    fixenv.canaries_break, fixenv.win.refuse_restore = True, True
    res = fixenv.agent().fix(make_inv(), manual=True, snap=fixenv.snap)
    assert res["state"] == "rolled_back" and "Access is denied" in res["rollback"]
    e, = netjournal.entries()
    assert e["state"] == "applied" and e["before"]["static_v4"] == ["192.168.1.1"]


def test_windows_refusing_the_change_leaves_nothing_behind(fixenv):
    fixenv.win.refuse_fix = True
    res = fixenv.agent().fix(make_inv(), manual=True, snap=fixenv.snap)
    assert res["state"] == "failed" and "Access is denied" in res["reasons"][0]
    assert netjournal.entries() == [] and fixenv.win.sets[-1]["restore"]      # restored in case of a partial apply


def test_fix_refuses_without_touching_anything(fixenv):
    a = fixenv.agent(tunnel=types.SimpleNamespace(connected=True))
    res = a.fix(make_inv(), manual=True, snap=fixenv.snap)
    assert res["state"] == "refused" and fixenv.win.scripts == [] and netjournal.entries() == []
    fixenv.win.unreadable = True
    res = fixenv.agent().fix(make_inv(), manual=True, snap=fixenv.snap)
    assert res["state"] == "refused" and "current DNS settings" in res["reasons"][0] and fixenv.win.sets == []


def test_user_rollback_restores_and_drops_profile(fixenv):
    a = fixenv.agent()
    res = a.fix(make_inv(), manual=True, snap=fixenv.snap)
    assert fixenv.win.current == ["8.8.8.8", "1.1.1.1"]
    assert a.rollback(res["entry"]) == {"ok": True, "detail": "DNS on Wi-Fi restored"}
    assert fixenv.win.current == ["192.168.1.1"] and netjournal.entries() == [] and json.load(open(agent.PROFILES)) == {}
    assert a.rollback(res["entry"]) == {"ok": False, "error": "no such change"}


def test_fix_follows_the_network(fixenv, monkeypatch):
    a = fixenv.agent(dict(SETTINGS, ni_autofix=True))
    a.fix(make_inv(), manual=True, snap=fixenv.snap)
    home = fixenv.snap
    monkeypatch.setattr(investigate, "investigate_site", lambda name, *x, **k: make_inv())
    fixenv.snap = home_snap(gw4=[{"nh": "10.0.0.1", "metric": 0}], dhcpdns="10.0.0.1")    # hotel Wi-Fi
    a.on_network_change()
    assert netjournal.entries() == [] and fixenv.win.current == ["192.168.1.1"]
    fixenv.snap = home                                                                 # back home: re-applied
    a.on_network_change()
    e, = netjournal.entries()
    assert e["state"] == "applied" and e["auto"] is True and fixenv.win.current == ["8.8.8.8", "1.1.1.1"]


def test_fix_busy_lock(fixenv):
    a = fixenv.agent()
    a.lock.acquire()
    try:
        assert a.fix(make_inv())["state"] == "busy"
    finally:
        a.lock.release()


# ====================================================================== probes: pure logic
def test_sni_filter_check_classification(monkeypatch):
    def mk(real_err, neutral):
        def tls(ip, sni, port=443, timeout=4.0):
            if sni == TARGET:
                return {"ip": ip, "sni": sni, "tcp_ok": True, "tls_ok": False, "error": real_err}
            return neutral
        monkeypatch.setattr(probes, "tls_probe", tls)
        return probes.sni_filter_check(REAL[0], TARGET)["sni_filtered"]
    reached = {"tcp_ok": True, "tls_ok": False, "error": "tls-error"}
    assert mk("reset", reached) and mk("timeout", {"tcp_ok": True, "tls_ok": True})
    assert not mk("reset", {"tcp_ok": True, "tls_ok": False, "error": "reset"})      # both cut: not name-based
    assert not mk("cert-mismatch", reached)                                          # server answered the real name
    assert not mk("reset", {"tcp_ok": False, "tls_ok": False, "error": "timeout"})


def test_interception_test_flags_any_answer_from_nowhere(monkeypatch):
    def q(name, rtype="A", server="", timeout=1.5, **k):
        if server == "198.51.100.53":
            return dns_result(server, name, rtype, [rr(name, "A", "192.168.1.1")])
        return dns_result(server, name, rtype, error="timeout")
    monkeypatch.setattr(dnswire, "query", q)
    r = probes.interception_test()
    assert r["intercepted"] and [p["answered"] for p in r["probes"]] == [False, True]
    assert r["probes"][1]["answers"] == ["192.168.1.1"]
    monkeypatch.setattr(dnswire, "query", lambda name, rtype="A", server="", timeout=1.5, **k: dns_result(server, name, rtype, error="timeout"))
    r = probes.interception_test(v6=True)
    assert not r["intercepted"] and len(r["probes"]) == 3


def test_probe_error_kinds():
    assert probes._err_kind(socket.timeout("timed out")) == "timeout"
    assert probes._err_kind(ConnectionResetError()) == "reset"
    assert probes._err_kind(ConnectionRefusedError()) == "refused"
    assert probes._err_kind(OSError("Network is unreachable")) == "unreachable"
    import ssl
    assert probes._err_kind(ssl.SSLCertVerificationError("hostname mismatch")) == "cert-mismatch"
    assert probes._err_kind(ssl.SSLCertVerificationError("self signed")) == "cert-untrusted"
    assert probes._err_kind(ssl.SSLError("bad")) == "tls-error"
    assert probes._names({"subjectAltName": (("DNS", "a.com"), ("IP Address", "1.2.3.4")),
                          "issuer": ((("organizationName", "Let's Encrypt"),),)}) == (["a.com"], "Let's Encrypt")
    assert probes._names({"subject": ((("commonName", "b.com"),),)}) == (["b.com"], None)
