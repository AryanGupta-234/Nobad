"""NOBAD Evil Twin: a trust check for the network you just joined (public Wi-Fi first of all).

About ten seconds of real measurements, run side by side the moment the network changes (or when asked):

  dns-intercept   DNS sent to addresses where no server can exist gets an answer   -> something rewrites DNS on path
  dns-canary      names with fixed, published addresses (one.one.one.one, dns.google) resolve elsewhere
  dns-nxdomain    a random name that cannot exist resolves anyway                    -> resolver invents answers
  arp-spoof       the router's MAC is also claimed by another device on the LAN      -> someone poses as the router
  router-changed  this network's router MAC differs from the one recorded before
  wifi-security   open (no password) or WEP Wi-Fi                                     -> anyone nearby can read/copy it
  evil-twin       the same Wi-Fi name is broadcast with different security, or from an access point never seen here
  captive         a sign-in page intercepts plain web traffic
  tls-intercept   HTTPS to well-known sites presents a certificate for another name / an unknown issuer
  proxy           Windows was told to use a proxy (WPAD / manual) on this network

Each check gives pass / warn / fail / skip with the evidence. The score starts at 100; findings subtract points and
the critical ones (someone actively intercepting) cap the grade. Grade A..F; below the grade set in Settings NOBAD
connects the VPN by itself (same rules as "Connect on untrusted networks": never after a manual disconnect).

It builds on trust.py: the trusted-network fingerprint is the baseline for "router changed" / "new access point",
and a network that fails here is never treated as trusted. Nothing is changed on the system by the checks."""
import json
import os
import random
import re
import string
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import netinfo, trust
from .logbus import broadcast, log
from .syscmd import run

GRADES = ("A", "B", "C", "D", "F")
CANARIES = {"one.one.one.one": {"1.1.1.1", "1.0.0.1", "2606:4700:4700::1111", "2606:4700:4700::1001"},
            "dns.google": {"8.8.8.8", "8.8.4.4", "2001:4860:4860::8888", "2001:4860:4860::8844"}}
TLS_HOSTS = ("www.cloudflare.com", "www.google.com", "www.microsoft.com")
WEAK_AUTH = ("wep", "shared")
BASELINE_MAX = 60          # networks remembered for "router changed" / "new access point"


def grade_of(score, caps=()):
    g = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 55 else "F"
    for c in caps:                       # an active attack can't be outweighed by everything else passing
        if GRADES.index(c) > GRADES.index(g):
            g = c
    return g


def below(grade, threshold):
    """True when `grade` is worse than `threshold` ('off' never triggers)."""
    if threshold not in GRADES or grade not in GRADES:
        return False
    return GRADES.index(grade) > GRADES.index(threshold)


def _c(cid, title, state, detail="", points=0, cap=None, evidence=()):
    return {"id": cid, "title": title, "state": state, "detail": detail, "points": points, "cap": cap,
            "evidence": list(evidence)}


# ---------------------------------------------------------------------------------------------- parsers (pure)
_NET = re.compile(r"^SSID\s+\d+\s*:\s*(.*)$")
_KV = re.compile(r"^\s*([A-Za-z0-9 ]+?)\s*:\s*(.*)$")     # digits: "BSSID 1 : aa:bb:..."


def parse_networks(netsh_output):
    """`netsh wlan show networks mode=bssid` -> [{'ssid', 'auth', 'bssids': [...]}]."""
    out, cur = [], None
    for line in (netsh_output or "").splitlines():
        m = _NET.match(line.strip())
        if m:
            cur = {"ssid": m.group(1).strip(), "auth": None, "bssids": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        kv = _KV.match(line)
        if not kv:
            continue
        k, v = kv.group(1).strip().lower(), kv.group(2).strip()
        if k == "authentication":
            cur["auth"] = v
        elif k.startswith("bssid"):
            mac = netinfo.norm_mac(v)
            if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac):
                cur["bssids"].append(mac)
    return out


_ARP_IF = re.compile(r"^Interface:\s*([0-9.]+)", re.I)
_ARP_ROW = re.compile(r"^\s*([0-9.]+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\w+)")


def parse_arp(arp_output):
    """`arp -a` -> {interface_ip: {ip: mac}} (dynamic unicast entries only)."""
    out, cur = {}, None
    for line in (arp_output or "").splitlines():
        m = _ARP_IF.match(line.strip())
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        r = _ARP_ROW.match(line)
        if cur is None or not r or r.group(3).lower() != "dynamic":
            continue
        mac = netinfo.norm_mac(r.group(2))
        first = int(mac[:2], 16)
        if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") or first & 1:     # broadcast / multicast
            continue
        cur[r.group(1)] = mac
    return out


def arp_spoof_check(table, gw):
    """The router's MAC also answering for other LAN addresses is how ARP spoofing looks from the victim's side
    (the attacker claims the router's IP with its own MAC, or answers for many IPs at once)."""
    for _iface, rows in table.items():
        if gw not in rows:
            continue
        mac = rows[gw]
        others = sorted(ip for ip, m in rows.items() if m == mac and ip != gw)
        if others:
            return _c("arp-spoof", "Someone may be posing as the router", "fail",
                      f"the router's hardware address {mac} is also used by {', '.join(others[:4])}",
                      45, "F", [f"ARP: {gw} -> {mac}"] + [f"ARP: {ip} -> {mac}" for ip in others[:4]])
        return _c("arp-spoof", "Router identity (ARP)", "pass", f"{gw} answers as {mac}, and only it does")
    return _c("arp-spoof", "Router identity (ARP)", "skip", "the router isn't in the ARP table yet")


def proxy_from_reg(text):
    """`reg query ...Internet Settings` -> (manual_proxy | None, autoconfig_url | None)."""
    vals = {}
    for line in (text or "").splitlines():
        p = line.split(None, 2)
        if len(p) == 3 and p[1].startswith("REG_"):
            vals[p[0]] = p[2].strip()
    manual = vals.get("ProxyServer") if vals.get("ProxyEnable", "0x0").lower() not in ("0x0", "0") else None
    return manual, vals.get("AutoConfigURL")


# ---------------------------------------------------------------------------------------------- the checks
def _random_name():
    return "nb" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(18)) + ".com"


def check_dns_intercept(probes):
    r = probes.interception_test(False)
    if r.get("intercepted"):
        return _c("dns-intercept", "DNS is intercepted on this network", "fail",
                  "queries to addresses where no DNS server exists were answered", 35, "D",
                  [f"{p['target']} answered {p.get('rcode')}" for p in r["probes"] if p.get("answered")])
    return _c("dns-intercept", "DNS interception", "pass", "DNS goes where it is sent")


def check_dns_canary(probes):
    bad, ok = [], 0
    for name, want in CANARIES.items():
        got = probes.os_resolve(name, timeout=4)
        if not got.get("ok"):
            continue
        ips = set(got.get("ips") or [])
        if ips and not ips & want:
            bad.append(f"{name} -> {', '.join(sorted(ips)[:3])} (published: {', '.join(sorted(want)[:2])})")
        else:
            ok += 1
    if bad:
        return _c("dns-canary", "DNS answers are being redirected", "fail",
                  "names with fixed, public addresses resolve somewhere else", 35, "D", bad)
    if not ok:
        return _c("dns-canary", "DNS redirection", "skip", "the test names didn't resolve")
    return _c("dns-canary", "DNS redirection", "pass", "well-known names resolve to their published addresses")


def check_dns_nxdomain(probes):
    n = _random_name()
    got = probes.os_resolve(n, timeout=4)
    if got.get("ok") and got.get("ips"):
        return _c("dns-nxdomain", "The resolver invents answers", "warn",
                  "a name that cannot exist resolved to an address (ad/redirect or hijacking resolver)", 12,
                  evidence=[f"{n} -> {', '.join(got['ips'][:3])}"])
    return _c("dns-nxdomain", "Made-up names", "pass", "names that don't exist correctly fail")


def check_wifi(ident, scan):
    """Security of the joined Wi-Fi, and evil-twin signs in the scan of nearby networks."""
    out = []
    if not ident or ident.get("kind") != "wifi":
        return [_c("wifi-security", "Wi-Fi security", "skip", "wired network"),
                _c("evil-twin", "Look-alike networks", "skip", "wired network")]
    auth = (ident.get("auth") or "").strip()
    if not auth:
        out.append(_c("wifi-security", "Wi-Fi security", "skip",
                      "Windows hides it without Location permission (Settings > Privacy > Location > desktop apps)"))
    elif trust.is_open(auth):
        out.append(_c("wifi-security", "Open Wi-Fi: no password", "fail",
                      "anyone nearby can join, watch unencrypted traffic, and copy this network's name", 30, "C"))
    elif any(w in auth.lower() for w in WEAK_AUTH):
        out.append(_c("wifi-security", "Outdated Wi-Fi security", "fail", f"{auth} can be broken in minutes", 25, "C"))
    else:
        out.append(_c("wifi-security", "Wi-Fi security", "pass", auth))
    name = ident.get("name")
    same = [n for n in (scan or []) if n.get("ssid") == name]
    auths = sorted({(n.get("auth") or "").strip() for n in same if n.get("auth")})
    if len(auths) > 1 and any(trust.is_open(a) for a in auths):
        out.append(_c("evil-twin", "Evil twin: the same name with different security", "fail",
                      f'"{name}" is broadcast as {" and ".join(auths)} - a copy of a network is usually open', 40, "F",
                      [f"{n.get('auth')}: {', '.join(n['bssids'][:3])}" for n in same]))
    elif len(auths) > 1:
        out.append(_c("evil-twin", "The same name with different security", "warn",
                      f'"{name}" is broadcast as {" and ".join(auths)}', 15))
    elif same or scan:
        out.append(_c("evil-twin", "Look-alike networks", "pass", f'only one kind of "{name}" nearby'))
    else:
        out.append(_c("evil-twin", "Look-alike networks", "skip", "Windows didn't list nearby networks (Location permission)"))
    return out


def check_baseline(ident, base):
    """Compared with what this network looked like before (and with its trusted fingerprint)."""
    if not ident or not ident.get("name"):
        return [_c("router-changed", "Same router as before", "skip", "no network")]
    prev = (base or {}).get(ident["name"]) or {}
    gw = netinfo.norm_mac(ident.get("gw_mac"))
    out = []
    if not prev or not gw:
        out.append(_c("router-changed", "Same router as before", "skip",
                      "first visit: recorded for next time" if gw else "couldn't read the router's address"))
    elif gw in prev.get("gw_macs", []):
        out.append(_c("router-changed", "Same router as before", "pass", gw))
    else:
        out.append(_c("router-changed", "A different router uses this network name", "warn",
                      f"router {gw}; before: {', '.join(prev.get('gw_macs', [])[:2])}", 20, "C"))
    b = netinfo.norm_mac(ident.get("bssid"))
    if ident.get("kind") == "wifi" and b and prev.get("bssids"):
        if b not in prev["bssids"]:
            out.append(_c("new-ap", "A new access point for this network", "warn",
                          f"access point {b} wasn't seen here before (normal in big buildings; suspicious at home)", 8))
    return out


def check_captive(captive_fn):
    c = captive_fn(timeout=4)
    if c.get("status") == "captive":
        return _c("captive", "A sign-in page intercepts web traffic", "warn",
                  "public hotspot: until you sign in, the network rewrites plain web pages", 10,
                  evidence=[f"portal: {c.get('portal')}"] if c.get("portal") else [])
    if c.get("status") == "offline":
        return _c("captive", "Internet access", "skip", "no internet yet")
    return _c("captive", "Sign-in page", "pass", "web traffic arrives untouched")


def check_tls(probes):
    from .netintel.investigate import cert_covers
    bad, ok = [], 0
    for host in TLS_HOSTS:
        got = probes.os_resolve(host, timeout=4)
        ips = [ip for ip in (got.get("ips") or []) if ":" not in ip]
        if not ips:
            continue
        t = probes.tls_probe(ips[0], host, timeout=5)
        if not t.get("tcp_ok"):
            continue
        if t.get("verify_ok") or (t.get("tls_ok") and cert_covers(t.get("names"), host)):
            ok += 1
        elif t.get("tls_ok"):
            bad.append(f"{host}: certificate for {', '.join((t.get('names') or ['?'])[:3])}"
                       + (f" issued by {t['issuer']}" if t.get("issuer") else ""))
    if len(bad) >= 2 or (bad and not ok):
        return _c("tls-intercept", "HTTPS is being intercepted", "fail",
                  "secure sites present certificates that aren't theirs: someone is reading encrypted traffic", 50, "F", bad)
    if bad:
        return _c("tls-intercept", "One HTTPS site presented a wrong certificate", "warn", bad[0], 15, evidence=bad)
    if not ok:
        return _c("tls-intercept", "HTTPS interception", "skip", "couldn't reach the test sites")
    return _c("tls-intercept", "HTTPS interception", "pass", f"{ok} well-known sites presented their own certificates")


def check_proxy(reg_text):
    manual, pac = proxy_from_reg(reg_text)
    if pac or manual:
        return _c("proxy", "Web traffic is sent through a proxy", "warn",
                  f"{'automatic script ' + pac if pac else 'proxy ' + manual} - fine at work, suspicious on public Wi-Fi", 15)
    return _c("proxy", "Proxy settings", "pass", "no proxy configured")


# ---------------------------------------------------------------------------------------------- orchestration
class EvilTwin:
    """Runs the checks, keeps the last report and the per-network baseline, and applies the auto-VPN rule."""

    def __init__(self, settings, tunnel=None, path=None, ident_fn=None, scan_fn=None, arp_fn=None, gw_fn=None,
                 reg_fn=None, captive_fn=None, probes=None, notify=None, connect=None):
        from .const import DATA_DIR
        from .netintel import probes as _probes
        self.settings, self.tunnel, self.notify = settings, tunnel, notify
        self.path = path or os.path.join(DATA_DIR, "eviltwin.json")
        self.ident_fn = ident_fn or netinfo.current_network_identity
        self.scan_fn = scan_fn or (lambda: parse_networks(run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=10).stdout))
        self.arp_fn = arp_fn or (lambda: parse_arp(run(["arp", "-a"], timeout=8).stdout))
        self.gw_fn = gw_fn or netinfo.default_gateway
        self.reg_fn = reg_fn or (lambda: run(["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"],
                                             timeout=6).stdout)
        self.captive_fn = captive_fn or netinfo.captive_check
        self.probes = probes or _probes
        self.connect = connect
        self.last = None
        self._lock = threading.Lock()
        self._manual_off = False

    # ---- baseline (what each network looked like before), stored only on this PC
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _remember(self, ident, report):
        if not ident or not ident.get("name") or report["grade"] in ("D", "F"):
            return                         # never learn a network while it looks attacked
        d = self._load()
        e = d.get(ident["name"]) or {}
        gw, b = netinfo.norm_mac(ident.get("gw_mac")), netinfo.norm_mac(ident.get("bssid"))
        if gw:
            e["gw_macs"] = ([x for x in e.get("gw_macs", []) if x != gw] + [gw])[-4:]
        if b:
            e["bssids"] = ([x for x in e.get("bssids", []) if x != b] + [b])[-16:]
        e["seen"], e["grade"] = time.time(), report["grade"]
        d[ident["name"]] = e
        if len(d) > BASELINE_MAX:
            for k in sorted(d, key=lambda k: d[k].get("seen", 0))[:len(d) - BASELINE_MAX]:
                d.pop(k, None)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(self.path + ".tmp", self.path)
        except OSError:
            pass

    def note_manual_disconnect(self):
        self._manual_off = True

    # ---- one run
    def run(self, reason="manual"):
        if not self._lock.acquire(blocking=False):
            return self.last
        try:
            rep = self._run(reason)
        finally:
            self._lock.release()
        self.last = rep
        broadcast("et_report", rep)
        self._act(rep)
        return rep

    def _run(self, reason):
        t0 = time.time()
        ident = self.ident_fn()
        if not ident:
            return {"ok": False, "error": "Not connected to a network.", "ts": time.time(), "reason": reason}
        connected = bool(self.tunnel is not None and getattr(self.tunnel, "connected", False))
        base = self._load()
        prints = (self.settings.get("trusted_fingerprints") or {}).get(ident["name"])
        if prints and not base.get(ident["name"]):
            base[ident["name"]] = {"gw_macs": prints.get("gw_macs", []), "bssids": prints.get("bssids", [])}
        jobs = {"wifi": lambda: check_wifi(ident, self.scan_fn() if ident.get("kind") == "wifi" else []),
                "arp": lambda: arp_spoof_check(self.arp_fn(), self.gw_fn()),
                "base": lambda: check_baseline(ident, base),
                "proxy": lambda: check_proxy(self.reg_fn())}
        if not connected:     # through the tunnel these would test the VPN, not this network
            jobs.update({"dns-i": lambda: check_dns_intercept(self.probes),
                         "dns-c": lambda: check_dns_canary(self.probes),
                         "dns-n": lambda: check_dns_nxdomain(self.probes),
                         "captive": lambda: check_captive(self.captive_fn),
                         "tls": lambda: check_tls(self.probes)})
        checks = []
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = {k: ex.submit(fn) for k, fn in jobs.items()}
            for k, f in futs.items():
                try:
                    r = f.result(timeout=25)
                except Exception as e:
                    r = _c(k, k, "skip", f"check failed: {type(e).__name__}")
                checks += r if isinstance(r, list) else [r]
        if connected:
            checks.append(_c("vpn", "DNS and HTTPS checks", "skip", "NOBAD VPN is connected: that traffic is already protected"))
        order = {"fail": 0, "warn": 1, "pass": 2, "skip": 3}
        checks.sort(key=lambda c: (order[c["state"]], -c["points"]))
        score = max(0, 100 - sum(c["points"] for c in checks if c["state"] in ("fail", "warn")))
        g = grade_of(score, [c["cap"] for c in checks if c["cap"] and c["state"] in ("fail", "warn")])
        trusted, _why = trust.check(ident, self.settings.get("trusted_networks"), self.settings.get("trusted_fingerprints"))
        rep = {"ok": True, "network": ident["name"], "kind": ident.get("kind"), "grade": g, "score": score,
               "checks": checks, "vpn_connected": connected, "trusted": trusted == "trusted", "reason": reason,
               "ts": time.time(), "took_s": round(time.time() - t0, 1),
               "summary": summary(g, checks)}
        self._remember(ident, rep)
        log(f'Evil Twin check: "{ident["name"]}" grade {g} ({score}/100, {rep["took_s"]} s)',
            "bad" if g in ("D", "F") else "warn" if g == "C" else "info")
        return rep

    def _act(self, rep):
        if not rep or not rep.get("ok") or rep.get("vpn_connected"):
            return
        thr = self.settings.get("et_vpn_below") or "off"
        t = self.tunnel
        if below(rep["grade"], thr) and t is not None and not t.connected and not getattr(t, "connecting", False) \
                and not self._manual_off:
            target = self.settings.get("last_region") or (t.region_names()[0] if t.region_names() else None)
            if target and t.has_region(target):
                log(f'Evil Twin: "{rep["network"]}" is grade {rep["grade"]} (below {thr}) - connecting {target}', "warn")
                if self.notify:
                    self.notify(f"Network grade {rep['grade']}", f'"{rep["network"]}": {rep["summary"]} '
                                f"NOBAD is connecting the VPN.", "eviltwin", "warn")
                (self.connect or t.connect)(target)
                rep["action"] = "connected"
                return
        if rep["grade"] in ("D", "F") and self.notify:
            self.notify(f"Network grade {rep['grade']}", f'"{rep["network"]}": {rep["summary"]} Connect NOBAD before '
                        "you sign in to anything.", "eviltwin", "bad")

    # ---- wiring
    def on_network_change(self, *_a, **_k):
        if not self.settings.get("et_enabled"):
            return
        self._manual_off = False           # a new network gets a fresh decision
        time.sleep(2)                      # let DHCP and the ARP table settle
        try:
            self.run("network change")
        except Exception as e:
            log(f"Evil Twin check failed: {e}", "warn")


def summary(grade, checks):
    bad = [c["title"] for c in checks if c["state"] == "fail"]
    warn = [c["title"] for c in checks if c["state"] == "warn"]
    if bad:
        return bad[0] + "."
    if warn:
        return warn[0] + "."
    return {"A": "Nothing suspicious found.", "B": "Looks safe."}.get(grade, "Some checks couldn't run.")

