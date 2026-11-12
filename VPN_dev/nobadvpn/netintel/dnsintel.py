"""DNS intelligence: ask many resolvers the same question (in parallel), then compare what they say.

Resolver groups (all discovered at run time, see investigate.resolver_set):
  network    - what the network hands out via DHCP (router / ISP default)
  configured - what Windows is set to use right now
  reference  - independent resolvers from the user-editable `ni_reference_dns` setting
  encrypted  - DNS-over-HTTPS endpoints Windows itself has templates for (cannot be intercepted on the path)

Nothing about specific ISPs, resolvers or domains is built in. A finding is a set of generic signals with weights;
confidence = 1 - prod(1 - w) over the signals found, reduced by contradicting evidence."""
import ipaddress
import re
from concurrent.futures import ThreadPoolExecutor

from . import dnswire

# words used by DNS policy systems (RPZ zones, filtering products, ISP block pages) in synthetic names
POLICY_WORDS = ("rpz", "block", "blocked", "blocklist", "restricted", "restrict", "filter", "filtered", "sinkhole",
                "deny", "denied", "censor", "censored", "banned", "prohibited", "blackhole", "walledgarden", "notice",
                "warning", "unsafe", "malware", "phishing", "spam", "parental", "safesearch", "lawful", "court",
                "ministry", "dot-block", "govblock")
_SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu", "ne", "or", "go", "gob", "nic", "ltd", "plc", "sch"}


def registrable(name):
    """Approximate registrable domain (eTLD+1) without a public-suffix list: 'a.b.example.co.uk' -> 'example.co.uk'."""
    labels = [x for x in (name or "").lower().rstrip(".").split(".") if x]
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def policy_words_in(name):
    toks = re.split(r"[^a-z0-9]+", (name or "").lower())
    labels = (name or "").lower().split(".")
    hits = sorted({w for w in POLICY_WORDS if w in toks or any(lbl == w or lbl.startswith(w + "-") for lbl in labels)})
    return hits


def addr_class(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid"
    if a.is_unspecified:
        return "unspecified"
    if a.is_loopback:
        return "loopback"
    if a.is_private or a.is_link_local or a.is_reserved or a.is_multicast:
        return "non-public"
    return "public"


def chain_of(qname, res):
    """CNAME chain followed from the question name, plus final A/AAAA addresses and the lowest TTL."""
    by_owner = {}
    addrs = []
    ttls = []
    for rr in res.get("answers") or []:
        ttls.append(rr.get("ttl", 0))
        if rr["type"] == "CNAME":
            by_owner[rr["name"]] = rr["data"]
        elif rr["type"] in ("A", "AAAA"):
            addrs.append(rr["data"])
    chain, cur, seen = [], qname.lower().rstrip("."), set()
    while cur in by_owner and cur not in seen:
        seen.add(cur)
        cur = by_owner[cur]
        chain.append(cur)
    return {"cnames": chain, "addrs": sorted(set(addrs)), "min_ttl": min(ttls) if ttls else None}


def resolve_matrix(name, resolvers, types=("A", "AAAA"), timeout=2.5, workers=12):
    """resolvers: [{'ip' or 'doh', 'label', 'group'}]. Returns [{resolver..., 'results': {type: summary}}]."""
    jobs = []
    for r in resolvers:
        for t in types:
            jobs.append((r, t))

    def one(job):
        r, t = job
        if r.get("doh"):
            res = dnswire.query_doh(name, t, url=r["doh"], timeout=timeout + 2)
        else:
            res = dnswire.query(name, t, server=r["ip"], timeout=timeout)
        return r, t, res

    rows = {id(r): {**r, "results": {}} for r in resolvers}
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(jobs)))) as ex:
        for r, t, res in ex.map(one, jobs):
            rows[id(r)]["results"][t] = {
                "rcode": res["rcode_name"], "error": res["error"], "rtt_ms": res["rtt_ms"],
                "transport": res["transport"], **chain_of(name, res),
                "authority": [a["data"]["mname"] for a in res.get("authority") or [] if a["type"] == "SOA"][:1]}
    return [rows[id(r)] for r in resolvers]


def _answered(x):
    return x and x["rcode"] == "NOERROR" and x["addrs"]


def consensus(matrix, groups=("reference", "encrypted")):
    """What the independent resolvers agree on: addresses, CNAME targets, and how consistent they are."""
    refs = [m for m in matrix if m["group"] in groups]
    out = {"resolvers": len(refs), "addrs": set(), "cnames": set(), "nxdomain": 0, "answered": 0, "failed": 0,
           "agree": True}
    per = []
    for m in refs:
        got_any = False
        for t, x in m["results"].items():
            if _answered(x):
                got_any = True
                out["addrs"].update(x["addrs"])
                out["cnames"].update(x["cnames"])
            elif x and x["rcode"] == "NXDOMAIN":
                out["nxdomain"] += 1
        a = set().union(*[set(x["addrs"]) for x in m["results"].values() if _answered(x)]) if got_any else set()
        if got_any:
            out["answered"] += 1
            per.append(a)
        elif all(x["error"] for x in m["results"].values()):
            out["failed"] += 1
    if len(per) >= 2:
        out["agree"] = all(p & per[0] for p in per[1:])
    return out


def analyze(name, matrix, history_sinkholes=(), tls_evidence=None):
    """Findings for every non-independent resolver, compared with the independent consensus.
    tls_evidence: optional {'suspect': {ip: tls_probe}, 'consensus': {ip: tls_probe}} from investigate()."""
    cons = consensus(matrix)
    findings = []
    qreg = registrable(name)
    if cons["answered"] == 0:
        if cons["nxdomain"] >= min(2, cons["resolvers"]):
            findings.append(_finding("name-does-not-exist", "dns", "info", 0.9, name,
                                     f"{name} does not exist: every independent resolver says NXDOMAIN.",
                                     ["Check the spelling; this is not filtering."], []))
        elif cons["failed"]:
            findings.append(_finding("references-unreachable", "dns", "warn", 0.6, name,
                                     "None of the independent resolvers could be reached, so answers can't be compared.",
                                     ["Outbound DNS (port 53) may be blocked on this network; try the encrypted (DoH) check or connect NOBAD."],
                                     [f"{cons['failed']} of {cons['resolvers']} independent resolvers did not answer"]))
        return {"consensus": _cons_public(cons), "findings": findings}

    for m in matrix:
        if m["group"] not in ("network", "configured"):
            continue
        ev, w, contra = [], [], []
        label = m.get("label") or m.get("ip")
        rs = m["results"]
        a = rs.get("A") or {}
        all_addrs = sorted(set().union(*[set(x.get("addrs") or []) for x in rs.values()]))
        cn = sorted(set().union(*[set(x.get("cnames") or []) for x in rs.values()]))
        if all(x and x["error"] for x in rs.values()):
            findings.append(_finding("resolver-failed", "dns", "warn", 0.7, label,
                                     f"{label} did not answer ({a.get('error') or 'error'}) while independent resolvers did.",
                                     ["This is a resolver failure, not filtering. Restarting the router or switching DNS helps."],
                                     [f"{label}: {', '.join(sorted({x['error'] for x in rs.values() if x}))}"], m))
            continue
        if any(x and x["rcode"] in ("SERVFAIL", "REFUSED") for x in rs.values()) and not all_addrs:
            findings.append(_finding("resolver-error", "dns", "warn", 0.65, label,
                                     f"{label} returned {a.get('rcode')} for {name}; independent resolvers answered normally.",
                                     ["Usually a resolver or DNSSEC problem on that server, not deliberate filtering."],
                                     [f"{label}: rcode {a.get('rcode')}"], m))
            continue
        if any(x and x["rcode"] == "NXDOMAIN" for x in rs.values()):
            ev.append(f"{label} says {name} does not exist (NXDOMAIN); {cons['answered']} independent resolver(s) return addresses")
            w.append(0.45)
        extra_cn = [c for c in cn if c not in cons["cnames"] and registrable(c) != qreg]
        if extra_cn:
            ev.append(f"{label} redirects {name} via CNAME to {', '.join(extra_cn)} - a different domain that no independent resolver returns")
            w.append(0.35)
            pw = sorted({p for c in extra_cn for p in policy_words_in(c)})
            if pw:
                rpz = "rpz" in pw
                ev.append(("the redirect target uses RPZ-style naming ('rpz' label): DNS Response Policy Zones are how resolvers rewrite blocked names"
                           if rpz else f"the redirect target contains policy words: {', '.join(pw)}"))
                w.append(0.35 if rpz else 0.22)
        if all_addrs:
            odd = [ip for ip in all_addrs if addr_class(ip) != "public"]
            if odd and all(addr_class(ip) == "public" for ip in cons["addrs"]):
                ev.append(f"{label} answers with non-public address(es) {', '.join(odd)} (typical sinkhole), independent resolvers give public ones")
                w.append(0.40)
            if not (set(all_addrs) & cons["addrs"]):
                ev.append(f"none of {label}'s addresses ({', '.join(all_addrs[:4])}) appear among the independent answers ({', '.join(sorted(cons['addrs'])[:4])})")
                w.append(0.15 if cons["agree"] else 0.07)
            else:
                contra.append(f"{label} shares at least one address with the independent resolvers")
            hs = sorted(set(all_addrs) & set(history_sinkholes))
            if hs:
                ev.append(f"{', '.join(hs)} was already seen answering for other blocked names on this network")
                w.append(0.25)
        te = tls_evidence or {}
        sus = [te.get("suspect", {}).get(ip) for ip in all_addrs if te.get("suspect", {}).get(ip)]
        good = [r for r in te.get("consensus", {}).values() if r and r.get("verify_ok")]
        if sus and good:
            if all(not r.get("verify_ok") for r in sus):
                names = sorted({n for r in sus for n in (r.get("names") or [])})[:4]
                ev.append(f"the address(es) from {label} do not present a valid certificate for {name}"
                          + (f" (they present {', '.join(names)})" if names else "")
                          + "; the independent addresses do")
                w.append(0.45)
            elif any(r.get("verify_ok") for r in sus):
                contra.append(f"an address from {label} serves a valid certificate for {name} (likely just a different server of the same site)")
        if not ev:
            continue
        conf = 1.0
        for x in w:
            conf *= (1 - x)
        conf = 1 - conf - 0.25 * len(contra)
        conf = max(0.05, min(0.99, conf))
        kind = "dns-filtering" if conf >= 0.3 else "dns-divergence"
        title = (f"{label} appears to filter {name} at the DNS level" if kind == "dns-filtering"
                 else f"{label} answers {name} differently from independent resolvers")
        findings.append(_finding(kind, "dns", "bad" if conf >= 0.55 else "warn", round(conf, 2), label, title, [], ev, m,
                                 contra=contra, filtered_ips=all_addrs, redirect=extra_cn))
    return {"consensus": _cons_public(cons), "findings": findings}


def _cons_public(c):
    return {"addrs": sorted(c["addrs"]), "cnames": sorted(c["cnames"]), "resolvers": c["resolvers"],
            "answered": c["answered"], "agree": c["agree"]}


def _finding(kind, layer, severity, confidence, subject, title, recommend, evidence, row=None, **extra):
    return {"kind": kind, "layer": layer, "severity": severity, "confidence": confidence,
            "confidence_label": "high" if confidence >= 0.8 else "medium" if confidence >= 0.55 else "low",
            "subject": subject, "title": title, "evidence": evidence, "recommend": recommend,
            "resolver": {k: row.get(k) for k in ("ip", "doh", "label", "group", "via")} if row else None, **extra}


def lookup(name, rtypes, resolvers, timeout=2.5):
    """DNS Intelligence tab: any record types against chosen resolvers, raw records included."""
    out = []
    for r in resolvers:
        row = {**r, "records": {}}
        for t in rtypes:
            res = dnswire.query_doh(name, t, url=r["doh"], timeout=timeout + 2) if r.get("doh") else \
                dnswire.query(name, t, server=r["ip"], timeout=timeout)
            row["records"][t] = {"rcode": res["rcode_name"], "error": res["error"], "rtt_ms": res["rtt_ms"],
                                 "answers": res["answers"], "authority": res["authority"]}
        out.append(row)
    return out
