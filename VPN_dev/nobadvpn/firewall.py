"""Kill-switch and DNS-leak rules (Windows Firewall via netsh). The rule *maths* is pure and unit-tested.

Kill switch: block outbound traffic whose SOURCE is not the tunnel address and whose DESTINATION is not
LAN / a configured endpoint. Traffic from the tunnel's own address is never matched.

DNS block: block outbound TCP/UDP 53 (and 853, DNS-over-TLS) from any source that is not the tunnel
address, including to LAN resolvers — so name lookups can only happen inside the tunnel.
"""
import ipaddress
import time

from .syscmd import run

KS_RULES = ("NobadKS4", "NobadKS6")
DNS_RULES = ("NobadDNS4U", "NobadDNS4T", "NobadDNS6U", "NobadDNS6T")
LEGACY_RULES = tuple("Nomad" + n[len("Nobad"):] for n in KS_RULES + DNS_RULES)  # rules created by NOMAD Tunnel
BRIDGE = "b"     # suffix of the temporary copy that keeps blocking while a rule is recreated
BRIDGE_RULES = tuple(n + BRIDGE for n in KS_RULES + DNS_RULES)
ALL_RULES = KS_RULES + DNS_RULES + BRIDGE_RULES
DNS_PORTS = "53,853"
_N = ipaddress.ip_network
LAN4 = [_N(x) for x in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "224.0.0.0/4",
                        "127.0.0.0/8", "255.255.255.255/32")]
LAN6 = [_N(x) for x in ("fe80::/10", "fc00::/7", "ff00::/8", "::1/128")]


def complement(version, excludes):
    universe = ipaddress.ip_network("0.0.0.0/0" if version == 4 else "::/0")
    ex = [e for e in excludes if e.version == version]
    nets = [universe]
    for e in ipaddress.collapse_addresses(ex):
        nxt = []
        for n in nets:
            if e.subnet_of(n):
                nxt.extend(n.address_exclude(e))
            elif n.subnet_of(e):
                continue
            else:
                nxt.append(n)
        nets = nxt
    return nets


def tunnel_nets(addrs):
    t4, t6 = [], []
    for a in addrs:
        ifc = ipaddress.ip_interface(a)
        net = _N(f"{ifc.ip}/{ifc.ip.max_prefixlen}")
        (t4 if ifc.version == 4 else t6).append(net)
    return t4, t6


def build_rules(addrs, endpoint_ips, kill_switch=True, dns_block=True):
    """Return a list of rule dicts: {name, protocol, remoteport, localip[list], remoteip[list]|None}."""
    t4, t6 = tunnel_nets(addrs)
    if not t4 and not t6:
        raise ValueError("config has no Address line")
    ep4 = [_N(f"{i}/32") for i in endpoint_ips if ":" not in i]
    ep6 = [_N(f"{i}/128") for i in endpoint_ips if ":" in i]
    loc4 = complement(4, t4 + [_N("127.0.0.0/8")])
    loc6 = complement(6, t6 + [_N("::1/128")])
    rules = []
    if kill_switch:
        rules.append({"name": KS_RULES[0], "protocol": "any", "remoteport": None, "localip": loc4,
                      "remoteip": complement(4, LAN4 + ep4)})
        rules.append({"name": KS_RULES[1], "protocol": "any", "remoteport": None, "localip": loc6,
                      "remoteip": complement(6, LAN6 + ep6)})
    if dns_block:
        for name, loc, proto in (("NobadDNS4U", loc4, "udp"), ("NobadDNS4T", loc4, "tcp"),
                                 ("NobadDNS6U", loc6, "udp"), ("NobadDNS6T", loc6, "tcp")):
            rules.append({"name": name, "protocol": proto, "remoteport": DNS_PORTS, "localip": loc, "remoteip": None})
    return rules


def _csv(nets):
    return ",".join(str(x) for x in nets)


def _add_cmd(r):
    cmd = ["netsh", "advfirewall", "firewall", "add", "rule", f"name={r['name']}", "dir=out", "action=block",
           "enable=yes", "profile=any", f"protocol={r['protocol']}"]
    if r["remoteport"]:
        cmd.append(f"remoteport={r['remoteport']}")
    cmd.append("localip=" + _csv(r["localip"]))
    if r["remoteip"]:
        cmd.append("remoteip=" + _csv(r["remoteip"]))
    return cmd


def _set_cmd(r):
    cmd = ["netsh", "advfirewall", "firewall", "set", "rule", f"name={r['name']}", "new",
           "localip=" + _csv(r["localip"])]
    if r["remoteip"]:
        cmd.append("remoteip=" + _csv(r["remoteip"]))
    return cmd


def firewall_enabled():
    """True if Windows Firewall is ON for every profile, False if any profile is OFF, None if unknown.
    Rules are useless while the firewall itself is off (e.g. disabled by a third-party firewall)."""
    r = run(["netsh", "advfirewall", "show", "allprofiles", "state"], timeout=15)
    if r.returncode != 0 or not r.stdout:
        return None
    states = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == "state":
            states.append(parts[-1].upper())
    if not states:
        return None  # localized output we can't read: don't claim anything
    return all(st == "ON" for st in states)


def rule_exists(name):
    return run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"], timeout=15).returncode == 0


def installed_names(names=ALL_RULES + LEGACY_RULES):
    """Which of `names` exist, from ONE netsh call (~0.9 s) instead of one call per rule (~0.3 s each).
    Matching is on the value after the first ':' so it works with localized netsh labels.
    Returns None if the listing itself failed (callers then fall back to per-rule commands)."""
    r = run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "dir=out"], timeout=30)
    if r.returncode != 0 and not r.stdout:
        return None
    want, found = set(names), set()
    for line in (r.stdout or "").splitlines():
        if ":" in line:
            v = line.split(":", 1)[1].strip()
            if v in want:
                found.add(v)
    return found


def present():
    """Names of NOBAD rules currently installed."""
    found = installed_names(ALL_RULES)
    if found is None:
        return [n for n in ALL_RULES if rule_exists(n)]
    return [n for n in ALL_RULES if n in found]


def legacy_present():
    """Rules left behind by NOMAD Tunnel (the previous product name)."""
    found = installed_names(LEGACY_RULES)
    if found is None:
        return [n for n in LEGACY_RULES if rule_exists(n)]
    return [n for n in LEGACY_RULES if n in found]


def remove(names=ALL_RULES, known=None):
    """Delete rules. With `known` (names known to exist) only those are deleted, saving a netsh call per
    absent rule; without it, everything named is deleted (safe default)."""
    for n in names:
        if known is not None and n not in known:
            continue
        run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={n}"])


def _try(cmd, attempts=3, pause=0.3):
    for i in range(attempts):
        if run(cmd, timeout=30).returncode == 0:
            return True
        if i + 1 < attempts:
            time.sleep(pause)
    return False


def _delete(name):
    run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"])


def apply(rules):
    """Install `rules`, updating existing ones IN PLACE (no unprotected gap), and delete any stale Nobad rule
    that is not part of the new set. Returns {rule_name: bool}.

    When a rule can't be updated in place (protocol/port changes), a bridge copy of the NEW rule is added first,
    then the old rule is replaced, then the bridge is removed. So there is never a moment with no blocking rule,
    and if re-adding fails the bridge stays and keeps protecting (it is cleaned up like any other NOBAD rule)."""
    result = {}
    existing = set(present())
    keep = set()
    for r in rules:
        name = r["name"]
        keep.add(name)
        if name in existing and run(_set_cmd(r), timeout=30).returncode == 0:
            result[name] = True
            continue
        if name not in existing:
            result[name] = _try(_add_cmd(r))
            continue
        bridge = dict(r, name=name + BRIDGE)
        if bridge["name"] in existing:
            _delete(bridge["name"])
        bridged = _try(_add_cmd(bridge))
        _delete(name)
        ok = _try(_add_cmd(r))
        if ok and bridged:
            _delete(bridge["name"])
        elif bridged:
            keep.add(bridge["name"])    # the bridge is the rule now; it still blocks
        result[name] = ok or bridged
    remove([n for n in existing if n not in keep], known=existing)
    return result
