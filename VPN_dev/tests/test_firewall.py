import ipaddress as ip

from nobadvpn import firewall as fw


def covered(addr, nets):
    a = ip.ip_address(addr)
    return any(a in n for n in nets)


def rules(**kw):
    return {r["name"]: r for r in fw.build_rules(["10.2.0.2/32", "fd00::2/128"], ["203.0.113.9", "2001:db8::9"], **kw)}


def test_kill_switch_math():
    r = rules()
    ks4 = r["NobadKS4"]
    assert not covered("10.2.0.2", ks4["localip"])          # tunnel source never blocked
    assert covered("192.168.1.50", ks4["localip"])          # physical NIC blocked
    assert not covered("192.168.1.1", ks4["remoteip"])      # LAN stays reachable
    assert not covered("203.0.113.9", ks4["remoteip"])      # VPN endpoint stays reachable
    assert covered("8.8.8.8", ks4["remoteip"])              # internet blocked
    ks6 = r["NobadKS6"]
    assert not covered("fd00::2", ks6["localip"]) and covered("2a00::1", ks6["localip"])
    assert not covered("2001:db8::9", ks6["remoteip"]) and covered("2606:4700::1", ks6["remoteip"])


def test_dns_block_rules():
    r = rules()
    for name, proto in (("NobadDNS4U", "udp"), ("NobadDNS4T", "tcp"), ("NobadDNS6U", "udp"), ("NobadDNS6T", "tcp")):
        assert r[name]["protocol"] == proto and r[name]["remoteport"] == "53,853" and r[name]["remoteip"] is None
    assert not covered("10.2.0.2", r["NobadDNS4U"]["localip"])   # DNS from the tunnel address is allowed
    assert covered("192.168.1.50", r["NobadDNS4U"]["localip"])   # DNS from the real NIC (even to the router) blocked
    assert not covered("127.0.0.1", r["NobadDNS4U"]["localip"])  # local stub resolver untouched


def test_toggles():
    assert set(rules(kill_switch=False)) == {"NobadDNS4U", "NobadDNS4T", "NobadDNS6U", "NobadDNS6T"}
    assert set(rules(dns_block=False)) == {"NobadKS4", "NobadKS6"}


def test_ipv4_only_config():
    rs = fw.build_rules(["10.0.0.2/32"], ["1.2.3.4"])
    names = {r["name"]: r for r in rs}
    assert covered("fd00::1", names["NobadKS6"]["localip"])     # no v6 tunnel address => all v6 blocked


def test_requires_address():
    import pytest
    with pytest.raises(ValueError):
        fw.build_rules([], [])


def test_complement_is_exact():
    c = fw.complement(4, [ip.ip_network("10.0.0.0/8")])
    assert sum(n.num_addresses for n in c) == 2 ** 32 - 2 ** 24
