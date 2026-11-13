"""Network Intelligence orchestration: overview, site investigation, VPN integrity.

Each entry point measures, compares with independent evidence and local history, and returns findings that carry
their evidence, a confidence and recommendations. Runs only when asked (or when the opt-in fix agent asks):
there is no background polling here."""
import ipaddress
import random
import re
import socket
import string
import time
from concurrent.futures import ThreadPoolExecutor

from . import dnsintel, dnswire, history, probes, system

GENERIC_WORDS = {"static", "dynamic", "broadband", "host", "hosts", "pool", "customer", "client", "users", "user",
                 "dsl", "adsl", "fiber", "fibre", "cable", "mobile", "wireless", "limited", "private", "public",
                 "services", "service", "network", "networks", "internet", "online", "global", "group", "corp",
                 "company", "india", "arpa", "addr", "reverse", "ptr", "dhcp", "ipv4", "ipv6", "home", "business"}
_NAME_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")


def normalize_target(target):
    """'https://Example.com:8443/path?q' -> 'example.com'. Raises ValueError for anything that isn't a hostname."""
    t = (target or "").strip().lower()
    t = re.sub(r"^[a-z][a-z0-9+.-]*://", "", t)
    t = t.split("/")[0].split("?")[0].split("#")[0]
    if t.startswith("[") or t.count(":") > 1:
        raise ValueError("enter a site name, not an IP address")
    t = t.split(":")[0].rstrip(".")
    try:
        t = t.encode("idna").decode() if any(ord(c) > 127 for c in t) else t
    except UnicodeError:
        raise ValueError("not a valid site name")
    try:
        ipaddress.ip_address(t)
        raise ValueError("enter a site name, not an IP address")
    except ValueError as e:
        if "site name" in str(e):
            raise
    if not _NAME_RE.match(t):
        raise ValueError("not a valid site name")
    return t


def reference_ips(settings, v6=True):
    raw = str(settings.get("ni_reference_dns") or "")
    out = []
    for p in raw.replace(";", ",").split(","):
        p = p.strip()
        try:
            a = ipaddress.ip_address(p)
        except ValueError:
            continue
        if a.version == 6 and not v6:
            continue
        if p not in out:
            out.append(p)
    return out


def resolver_set(snap, settings, include_doh=True):
    """Which resolvers to compare, all discovered now: the network's (DHCP), Windows' configured ones, the user's
    independent references (minus any already in use), and Windows' own DoH templates for those references."""
    rows, seen = [], {}
    for r in system.network_resolvers(snap):
        seen[r["ip"]] = len(rows)
        rows.append({"ip": r["ip"], "label": f"Network DNS {r['ip']}", "group": "network", "via": "dhcp", "in_use": False})
    for r in system.system_resolvers(snap):
        if r["ip"] in seen:
            rows[seen[r["ip"]]]["in_use"] = True
            continue
        seen[r["ip"]] = len(rows)
        rows.append({"ip": r["ip"], "label": f"Windows DNS {r['ip']}" + (" (tunnel)" if r["via"] == "tunnel" else ""),
                     "group": "configured", "via": r["via"], "in_use": True})
    refs = [ip for ip in reference_ips(settings, v6=snap.get("v6_available", False)) if ip not in seen]
    for ip in refs:
        rows.append({"ip": ip, "label": f"Independent {ip}", "group": "reference", "via": "direct", "in_use": False})
    if include_doh:
        all_refs = reference_ips(settings, v6=True)
        tmpl = [d for d in snap.get("doh_templates", []) if d.get("server") in all_refs and str(d.get("template", "")).startswith("https://")]
        used = set()
        for d in tmpl:
            if d["template"] in used:
                continue
            used.add(d["template"])
            rows.append({"doh": d["template"], "label": f"Encrypted {d['template'].split('/')[2]}", "group": "encrypted",
                         "via": "doh", "in_use": False})
            if len(used) >= 2:
                break
    return rows


def _rand_label(n=12):
    return "nb" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def _owner(snap, ip):
    for a in snap.get("adapters", []):
        for x in a["ipv4"] + a["ipv6"]:
            if x["ip"].split("%")[0] == ip:
                return a
    return None


def _ptr(ip, servers):
    for s in servers:
        r = dnswire.query(dnswire.ptr_name(ip), "PTR", server=s, timeout=2)
        names = [a["data"] for a in r["answers"] if a["type"] == "PTR"]
        if names:
            return names[0]
    return None


def _tokens(*texts):
    out = set()
    for t in texts:
        for tok in re.split(r"[^a-z0-9]+", (t or "").lower()):
            if len(tok) >= 4 and not tok.isdigit() and tok not in GENERIC_WORDS and tok not in dnsintel.POLICY_WORDS:
                out.add(tok)
    return out


def _token_matches(prov, tgt):
    """Provider words that also name the redirect/sinkhole. Exact, or one word starting the other when the shorter
    one is distinctive (>= 5 letters): 'airtel' matches 'airtelspam', 'comcast' matches 'comcastblock'."""
    out = set(prov & tgt)
    for p in prov:
        for t in tgt:
            a, b = (p, t) if len(p) <= len(t) else (t, p)
            if len(a) >= 5 and b.startswith(a):
                out.add(p)
    return out


def _finding(kind, layer, severity, confidence, title, evidence, recommend=(), **extra):
    return {"kind": kind, "layer": layer, "severity": severity, "confidence": round(confidence, 2),
            "confidence_label": "high" if confidence >= 0.8 else "medium" if confidence >= 0.55 else "low",
            "title": title, "evidence": list(evidence), "recommend": list(recommend), **extra}


def _par(fn, items, workers=8):
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        return list(ex.map(fn, items))


# ====================================================================== site investigation
def investigate_site(target, settings, tunnel=None, home=None, exit_info=None, snap=None):
    t0 = time.time()
    name = normalize_target(target)
    tname = tunnel.active if tunnel is not None and getattr(tunnel, "connected", False) else None
    snap = snap or system.snapshot(tname)
    if "error" in snap:
        return {"target": name, "ok": False, "error": snap["error"], "findings": []}
    key = history.network_key(snap)
    hist_on = bool(settings.get("ni_history"))
    findings = []
    if not snap.get("v4_available") and not snap.get("v6_available"):
        findings.append(_finding("offline", "local", "bad", 0.95, "This PC has no route to the internet",
                                 ["no adapter has a default route"], ["Check Wi-Fi / Ethernet, then run Quick network repair."]))
        return _done(name, snap, key, findings, {}, t0, hist_on, verdict="local-network")

    resolvers = resolver_set(snap, settings)
    bg = ThreadPoolExecutor(max_workers=2)        # independent of the DNS comparison: run alongside it
    f_inter = bg.submit(probes.interception_test, snap.get("v6_available", False))
    f_os = bg.submit(probes.os_resolve, name)
    matrix = dnsintel.resolve_matrix(name, resolvers)
    osr = f_os.result()
    cons = dnsintel.consensus(matrix)
    cons_v4 = [ip for ip in sorted(cons["addrs"]) if ":" not in ip][:2]
    cons_v6 = [ip for ip in sorted(cons["addrs"]) if ":" in ip][:1] if snap.get("v6_available") else []
    suspect = sorted({ip for m in matrix if m["group"] in ("network", "configured")
                      for x in m["results"].values() for ip in (x.get("addrs") or []) if ip not in cons["addrs"]})[:3]
    tls = dict(zip(suspect + cons_v4 + cons_v6, _par(lambda ip: probes.tls_probe(ip, name, timeout=4), suspect + cons_v4 + cons_v6)))
    tls_ev = {"suspect": {ip: tls[ip] for ip in suspect}, "consensus": {ip: tls[ip] for ip in cons_v4 + cons_v6}}
    dns = dnsintel.analyze(name, matrix, history.sinkholes(key).keys(), tls_ev)
    findings += dns["findings"]
    filt = [f for f in dns["findings"] if f["kind"] == "dns-filtering"]
    filtered_ips = sorted({ip for f in filt for ip in f.get("filtered_ips", [])})

    # ---- what applications on this PC actually get
    affected = None
    if osr.get("ok") and cons["addrs"]:
        got = set(osr["ips"])
        if filtered_ips and got & set(filtered_ips) and not got & cons["addrs"]:
            affected = True
        elif got & cons["addrs"] or (not filtered_ips):
            affected = False
    elif not osr.get("ok") and cons["addrs"]:
        affected = bool(filt) or None
        if not filt:
            findings.append(_finding("os-resolution-failed", "dns", "warn", 0.6,
                                     f"Windows can't resolve {name} ({osr.get('error')}) although independent resolvers can",
                                     [f"getaddrinfo: {osr.get('error')}"],
                                     ["Check the hosts file and any DNS policy (NRPT) or security software on this PC."]))
    for f in filt:
        in_use = (f.get("resolver") or {}).get("ip") in [r.get("ip") for r in resolvers if r.get("in_use")]
        f["in_use"] = in_use
        if affected is False and not in_use:
            f["note"] = ("Windows is not using this resolver right now, so apps on this PC already get the correct address. "
                         "Other devices on this network that use it are affected.")
    history.note_filtered(key, name, filtered_ips, enabled=hist_on)

    # ---- transport: does the REAL site answer from this network?
    reach = {}
    if cons_v4 or cons_v6:
        tcp = _par(lambda ip: probes.tcp_connect(ip, 443, 3), cons_v4 + cons_v6)
        reach = {r["ip"]: r for r in tcp}
        v4_ok = [r for r in tcp if r["ok"] and ":" not in r["ip"]]
        v6_ok = [r for r in tcp if r["ok"] and ":" in r["ip"]]
        if cons_v4 and not v4_ok:
            alt = _par(lambda ip: probes.tcp_connect(ip, 80, 3), cons_v4)
            findings.append(_finding(
                "ip-unreachable", "tcp", "bad", 0.7 if not any(a["ok"] for a in alt) else 0.5,
                f"The real addresses of {name} don't accept connections from this network",
                [f"TCP 443 to {r['ip']}: {r.get('error')}" for r in tcp if ":" not in r["ip"]]
                + [f"TCP 80 to {a['ip']}: {'open' if a['ok'] else a.get('error')}" for a in alt],
                ["This is not a DNS problem: changing DNS won't help.",
                 "Either the network blocks these IP addresses or the site is down. Connect NOBAD and try again to tell them apart."]))
        elif v4_ok:
            ip = v4_ok[0]["ip"]
            t = tls.get(ip) or probes.tls_probe(ip, name)
            if t["tcp_ok"] and not t["tls_ok"] and t.get("error") in ("reset", "timeout", "tls-error"):   # check SNI
                s = probes.sni_filter_check(ip, name)
                if s["sni_filtered"]:
                    findings.append(_finding(
                        "sni-filtering", "tls", "bad", 0.8, f"Connections to {name} are cut off by name (SNI filtering)",
                        [f"TLS to {ip} with the name {name}: connection {s['real'].get('error')}",
                         "TLS to the same address with a neutral name: the server answered"
                         + (f" ({s['neutral'].get('error')})" if s['neutral'].get('error') else ""),
                         "so the path to the server works; only handshakes that carry this site's name are cut off"],
                        ["The network inspects the site name in the TLS handshake. DNS changes won't help; use NOBAD VPN."]))
                else:
                    findings.append(_finding("tls-failed", "tls", "warn", 0.55, f"TLS to {name} fails ({t.get('error')})",
                                             [f"TLS to {ip}: {t.get('error')}"],
                                             ["Could be the site, a proxy or security software on this PC."]))
            elif t.get("verify_ok"):
                h = probes.http_probe(ip, name)
                if h.get("ok") and h.get("status") == 451:
                    findings.append(_finding("http-451", "http", "bad", 0.85, f"{name} answers 'Unavailable For Legal Reasons' (HTTP 451)",
                                             [f"GET https://{name}/ via {ip}: 451" + (f" - {h['title']}" if h.get("title") else "")],
                                             ["The block is applied by the site or its provider for your location; a VPN location elsewhere may work."]))
        if cons_v6 and v4_ok and not v6_ok:
            findings.append(_finding("ipv6-path-broken", "ipv6", "warn", 0.6, f"IPv6 to {name} fails while IPv4 works",
                                     [f"TCP 443 to {r['ip']}: {r.get('error')}" for r in tcp if ":" in r["ip"]],
                                     ["Apps may pause before falling back to IPv4. If this keeps happening, the router's IPv6 is broken."]))

    # ---- DNS interception on the path (affects every plain-DNS fix)
    inter = f_inter.result()
    bg.shutdown(wait=False)
    if inter["intercepted"]:
        findings.append(_finding("dns-interception", "dns", "bad", 0.9,
                                 "Something on this network intercepts DNS traffic",
                                 [f"{p['target']} (an address where no server can exist) answered: {p['rcode']} {', '.join(p['answers'])}"
                                  for p in inter["probes"] if p["answered"]],
                                 ["Switching Windows DNS won't escape it; use encrypted DNS (DoH) or NOBAD VPN."]))

    # ---- who operates the filtering (only with evidence)
    isp = isp_evidence(filt, snap, resolvers, home, exit_info, tunnel)
    if isp.get("matches"):
        for f in filt:
            f["evidence"].append(f"the redirect target shares the name '{', '.join(isp['matches'])}' with your provider ({isp['provider_label']}): "
                                 "the filtering is most likely done by your ISP")
            f["operator"] = isp
    verdict = _verdict(findings)
    recs = recommend(verdict, findings, affected, inter["intercepted"], tunnel)
    res = _done(name, snap, key, findings, {"matrix": matrix, "consensus": dns["consensus"], "os": osr, "tls": tls,
                                            "tcp": reach, "interception": inter, "isp": isp},
                t0, hist_on, verdict=verdict, affected=affected, recommendations=recs)
    return res


def isp_evidence(filt, snap, resolvers, home, exit_info, tunnel):
    refs = [r["ip"] for r in resolvers if r["group"] == "reference" and r.get("ip")][:2] or ["1.1.1.1"]
    connected = bool(tunnel is not None and getattr(tunnel, "connected", False))
    provider_texts, labels = [], []
    if exit_info and not connected and exit_info.get("org"):
        provider_texts.append(exit_info["org"])
        labels.append(exit_info["org"])
    pub = (home or {}).get("ip") if home else None
    if pub and not connected:
        p = _ptr(pub, refs)
        if p:
            provider_texts.append(p)
            labels.append(f"reverse DNS of your public IP: {p}")
    targets = [c for f in filt for c in f.get("redirect", [])]
    sink_ptrs = {}
    for ip in sorted({ip for f in filt for ip in f.get("filtered_ips", [])})[:2]:
        p = _ptr(ip, refs)
        if p:
            sink_ptrs[ip] = p
    prov = _tokens(*provider_texts)
    tgt = _tokens(*[dnsintel.registrable(t) for t in targets], *sink_ptrs.values())
    m = sorted(_token_matches(prov, tgt))
    return {"provider_label": "; ".join(labels) or None, "matches": m, "redirect_targets": targets,
            "sinkhole_ptr": sink_ptrs, "provider_known": bool(provider_texts),
            "note": None if provider_texts else "Turn on 'Look up my exit IP address' (Privacy) to let NOBAD name your provider."}


def _verdict(findings):
    kinds = {f["kind"] for f in findings if f["severity"] in ("bad", "warn")}
    for k in ("offline", "dns-interception", "sni-filtering", "ip-unreachable", "http-451", "dns-filtering",
              "resolver-failed", "resolver-error", "os-resolution-failed", "tls-failed", "ipv6-path-broken", "dns-divergence"):
        if k in kinds:
            return k
    if any(f["kind"] == "name-does-not-exist" for f in findings):
        return "name-does-not-exist"
    return "ok"


def recommend(verdict, findings, affected, intercepted, tunnel):
    connected = bool(tunnel is not None and getattr(tunnel, "connected", False))
    recs = []
    if verdict == "dns-filtering":
        if affected is False:
            recs.append({"id": "none", "text": "Nothing to do on this PC: Windows already uses a resolver that returns the real address."})
        else:
            if not connected:
                recs.append({"id": "vpn", "text": "Connect NOBAD: the tunnel's DNS bypasses your network's resolver.", "action": "vpn"})
            if intercepted:
                recs.append({"id": "doh", "text": "Your network intercepts plain DNS, so only encrypted DNS (DoH) or the VPN will work."})
            else:
                recs.append({"id": "dns", "text": "Switch Windows DNS on this network to an independent resolver that returned the real address. "
                             "NOBAD checks that nothing else breaks and undoes it automatically if something does.", "action": "dns_fix"})
        recs.append({"id": "more", "text": "Run 'Connectivity' to confirm the real site is reachable once DNS is fixed."})
    elif verdict in ("ip-unreachable", "sni-filtering"):
        recs.append({"id": "vpn", "text": "A DNS change won't help here. Connect NOBAD to reach the site.", "action": "vpn"} if not connected
                    else {"id": "server", "text": "Already connected: try a NOBAD server in another country."})
    elif verdict == "dns-interception":
        recs.append({"id": "vpn", "text": "Use NOBAD VPN (or encrypted DNS) so DNS can't be intercepted.", "action": "vpn"})
    elif verdict in ("resolver-failed", "resolver-error"):
        recs.append({"id": "dns", "text": "Your network's resolver is failing. Switching Windows DNS to an independent resolver fixes this.",
                     "action": "dns_fix"})
    for f in findings:
        for r in f.get("recommend", []):
            if r not in [x["text"] for x in recs]:
                recs.append({"id": "info", "text": r})
    return recs


def _done(name, snap, key, findings, data, t0, hist_on, **extra):
    res = {"target": name, "ok": True, "network_key": key, "ts": time.time(), "took_s": round(time.time() - t0, 1),
           "findings": findings, "data": data, "snapshot": {"primary": snap.get("primary"), "v6": snap.get("v6_available")}, **extra}
    history.append("investigation", {"target": name, "network": key, "verdict": extra.get("verdict"),
                                     "confidence": max([f["confidence"] for f in findings if f["severity"] != "info"] or [0]),
                                     "affected": extra.get("affected"),
                                     "titles": [f["title"] for f in findings][:6]}, enabled=hist_on)
    return res


# ====================================================================== overview
def overview(settings, tunnel=None):
    t0 = time.time()
    tname = tunnel.active if tunnel is not None and getattr(tunnel, "connected", False) else None
    snap = system.snapshot(tname)
    if "error" in snap:
        return {"ok": False, "error": snap["error"]}
    key = history.network_key(snap)
    hist_on = bool(settings.get("ni_history"))
    resolvers = [r for r in resolver_set(snap, settings, include_doh=False) if r.get("ip")]
    findings = []

    def health(r):
        root = dnswire.query(".", "NS", server=r["ip"], timeout=2.5)
        bogus = dnswire.query(_rand_label() + ".invalid", "A", server=r["ip"], timeout=2.5)
        bogus2 = dnswire.query(_rand_label() + ".example.com", "A", server=r["ip"], timeout=2.5)
        return {**r, "ok": root["rcode"] == 0, "rtt_ms": root["rtt_ms"] if root["rcode"] is not None else None,
                "error": root["error"], "rcode": root["rcode_name"],
                "nx_hijack": any(b["rcode_name"] == "NOERROR" and any(a["type"] == "A" for a in b["answers"]) for b in (bogus, bogus2)),
                "hijack_ips": sorted({a["data"] for b in (bogus, bogus2) for a in b["answers"] if a["type"] == "A"})}
    rh = _par(health, resolvers)
    inter = probes.interception_test(v6=snap.get("v6_available", False))
    for r in rh:
        if r["group"] in ("network", "configured"):
            if not r["ok"]:
                findings.append(_finding("resolver-down", "dns", "bad" if r.get("in_use") else "warn", 0.8,
                                         f"{r['label']} is not answering", [f"root query: {r['error'] or r['rcode']}"],
                                         ["Restart the router, or switch Windows DNS."]))
            if r["nx_hijack"]:
                findings.append(_finding("nxdomain-hijack", "dns", "warn", 0.85,
                                         f"{r['label']} invents answers for names that don't exist",
                                         [f"a random non-existent name resolved to {', '.join(r['hijack_ips'])}"],
                                         ["Typical of ISP 'search assist' / ad redirection. Typos and some apps get a fake page instead of an error."]))
    if inter["intercepted"]:
        findings.append(_finding("dns-interception", "dns", "bad", 0.9, "Something on this network intercepts DNS traffic",
                                 [f"{p['target']} answered although no server exists there" for p in inter["probes"] if p["answered"]],
                                 ["Plain DNS settings are overridden on the path; use DoH or NOBAD VPN."]))
    ups = [a for a in snap["adapters"] if (a["status"] or "").lower() == "up" and a["default4"] and a["role"] != "nobad-tunnel"]
    if len(ups) > 1:
        findings.append(_finding("multi-uplink", "routing", "info", 0.9, f"{len(ups)} adapters have a default route",
                                 [f"{a['name']} (metric {(a['route_metric4'] or 0) + (a['metric4'] or 0)})" for a in ups],
                                 ["Windows uses the lowest metric; the others are standby."]))
    p = system.adapter(snap, snap.get("primary"))
    if p and p.get("profile") and str(p["profile"].get("c6", "")).lower() == "internet" and not snap.get("v6_available"):
        findings.append(_finding("ipv6-inconsistent", "ipv6", "warn", 0.6, "Windows reports IPv6 internet but no global IPv6 route was found", [], []))
    dns_ms = [r["rtt_ms"] for r in rh if r.get("in_use") and r.get("rtt_ms") is not None]
    bl = history.compare_and_learn(key, system.signature(snap), min(dns_ms) if dns_ms else None, enabled=hist_on)
    for c in bl["changes"]:
        findings.append(_finding("changed", "network", "warn" if c["what"] in ("DNS servers", "gateway") else "info", 0.9,
                                 f"{c['what']} changed since this network was last seen",
                                 [f"before: {c['before']}", f"now: {c['now']}"],
                                 ["Expected if you changed it. Otherwise check the router: a changed DNS server can mean a hijacked router."]
                                 if c["what"] == "DNS servers" else []))
    res = {"ok": True, "ts": time.time(), "took_s": round(time.time() - t0, 1), "network_key": key, "baseline": bl,
           "snapshot": snap, "resolvers": rh, "interception": inter, "findings": findings,
           "sinkholes": history.sinkholes(key)}
    history.append("overview", {"network": key, "findings": [f["kind"] for f in findings], "resolvers": len(rh),
                                "v6": snap.get("v6_available")}, enabled=hist_on)
    return res


# ====================================================================== VPN integrity
def vpn_integrity(settings, tunnel, netwatch=None):
    if tunnel is None or not getattr(tunnel, "connected", False):
        return {"ok": True, "connected": False, "findings": [
            _finding("not-connected", "vpn", "info", 1.0, "Connect NOBAD to check the tunnel's integrity", [], [])]}
    snap = system.snapshot(tunnel.active)
    if "error" in snap:
        return {"ok": False, "error": snap["error"]}
    findings = []
    tun = system.adapter(snap, snap.get("tunnel"))
    up = system.adapter(snap, snap.get("primary"))
    if not tun:
        findings.append(_finding("tunnel-missing", "vpn", "bad", 0.9, "NOBAD reports connected, but no tunnel adapter is up",
                                 [f"expected an adapter named {tunnel.active}"], ["Reconnect; if it persists, export diagnostics."]))
    refs = reference_ips(settings, v6=True)
    checks = []
    for fam, af in (("IPv4", socket.AF_INET), ("IPv6", socket.AF_INET6)):
        dest = next((r for r in refs if (":" in r) == (af == socket.AF_INET6)), None)
        if not dest:
            continue
        src = _local_src(dest, af)
        owner = _owner(snap, src) if src else None
        via = owner["name"] if owner else None
        checks.append({"family": fam, "dest": dest, "source": src, "via": via, "tunnel": bool(owner and tun and owner["index"] == tun["index"])})
        if src and owner and tun and owner["index"] != tun["index"]:
            sev = "bad"
            ks = getattr(tunnel, "ks_active", False)
            findings.append(_finding(f"{fam.lower()}-outside-tunnel", "routing", "warn" if ks else sev, 0.85,
                                     f"{fam} traffic is routed outside the tunnel (via {via})",
                                     [f"route to {dest} leaves from {src} on {via}"] + (["the kill switch blocks it at the firewall"] if ks else []),
                                     ["Use a full-tunnel config (AllowedIPs 0.0.0.0/0, ::/0) or turn on the kill switch."]))
    if up and up.get("global_v6") and not any(c["family"] == "IPv6" and c["tunnel"] for c in checks):
        if not getattr(tunnel, "ks_active", False):
            findings.append(_finding("ipv6-leak-risk", "ipv6", "bad", 0.75, "IPv6 can bypass the tunnel",
                                     [f"{up['name']} has public IPv6 {up['global_v6'][0]} and IPv6 does not go through the tunnel"],
                                     ["Add ::/0 to AllowedIPs, or turn on the kill switch (it blocks IPv6 outside the tunnel)."]))
    leak_tests = []
    for d in (up or {}).get("dhcp_dns", [])[:2]:
        r = dnswire.query(".", "NS", server=d, timeout=2)
        leak_tests.append({"resolver": d, "answered": r["rcode"] is not None, "error": r["error"]})
        if r["rcode"] is not None:
            blocked_expected = bool(getattr(tunnel, "dns_active", False))
            findings.append(_finding("dns-leak-path", "dns", "bad" if blocked_expected else "warn", 0.8,
                                     f"DNS can still reach your network's resolver {d} outside the tunnel",
                                     [f"a direct DNS query to {d} was answered in {r['rtt_ms']} ms while connected"]
                                     + (["the DNS leak block is on, so this should have been blocked"] if blocked_expected else []),
                                     ["Turn on 'DNS leak block' in Settings."] if not blocked_expected else ["Reconnect to re-apply the firewall rules."]))
    tun_dns = (tun or {}).get("dns4", []) + (tun or {}).get("dns6", [])
    if tun and not tun_dns:
        findings.append(_finding("tunnel-no-dns", "dns", "warn", 0.7, "The tunnel has no DNS server",
                                 ["Windows will use the uplink's DNS servers for lookups"],
                                 ["Add a DNS line to the config, or enable 'Add a fallback DNS'."]))
    osr = probes.os_resolve(_rand_label() + ".invalid")
    transitions = [{"ts": t, "kind": k, "detail": d} for t, k, d in list(getattr(netwatch, "history", []) or [])[-8:]]
    if not findings:
        findings.append(_finding("integrity-ok", "vpn", "info", 0.85, "Tunnel integrity checks passed",
                                 [f"{c['family']} to {c['dest']} leaves through {c['via']}" for c in checks]
                                 + ([f"tunnel DNS: {', '.join(tun_dns)}"] if tun_dns else []), []))
    return {"ok": True, "connected": True, "tunnel": tunnel.active, "routes": checks, "tunnel_dns": tun_dns,
            "leak_tests": leak_tests, "kill_switch": bool(getattr(tunnel, "ks_active", False)),
            "dns_block": bool(getattr(tunnel, "dns_active", False)), "transitions": transitions,
            "invalid_name_resolves": bool(osr.get("ok")), "findings": findings, "ts": time.time()}


def _local_src(dest, family):
    s = None
    try:
        s = socket.socket(family, socket.SOCK_DGRAM)
        s.connect((dest, 53))
        return s.getsockname()[0].split("%")[0]
    except OSError:
        return None
    finally:
        if s:
            s.close()
