"""Local diagnostic history and per-network baselines (ProgramData\\NobadVPN\\netintel, never uploaded).

* history.jsonl - one line per investigation / overview (capped at MAX_LINES, oldest dropped)
* baselines.json - per network key: what 'normal' looks like (gateways, resolvers, IPv6, DNS latency), updated
                   with an exponential moving average so it adapts to a network over time
* sinkholes.json - addresses that answered for names found filtered, per network (sinkhole clusters)
Network keys are a hash of the uplink's gateway and the DHCP-offered DNS: no SSIDs or MAC addresses are stored."""
import hashlib
import json
import os
import threading
import time

from ..const import DATA_DIR

NI_DIR = os.path.join(DATA_DIR, "netintel")
MAX_LINES = 400
_lock = threading.RLock()


def _p(name):
    return os.path.join(NI_DIR, name)


def _read_json(name, default):
    try:
        with open(_p(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(name, data):
    os.makedirs(NI_DIR, exist_ok=True)
    tmp = _p(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _p(name))


def network_key(snap):
    from .system import adapter
    a = adapter(snap, snap.get("primary")) or {}
    raw = "|".join(sorted(a.get("gateways4", []))) + "#" + "|".join(sorted(a.get("dhcp_dns", []))) + "#" + (a.get("media") or "")
    return hashlib.sha256(raw.encode()).hexdigest()[:16] if a else "offline"


def append(kind, record, enabled=True):
    if not enabled:
        return
    line = json.dumps({"ts": time.time(), "kind": kind, **record}, separators=(",", ":"))
    with _lock:
        os.makedirs(NI_DIR, exist_ok=True)
        path = _p("history.jsonl")
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        lines = (lines + [line])[-MAX_LINES:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)


def recent(limit=60, kind=None):
    try:
        with open(_p("history.jsonl"), "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if kind and d.get("kind") != kind:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def clear():
    with _lock:
        for n in ("history.jsonl", "baselines.json", "sinkholes.json"):
            try:
                os.remove(_p(n))
            except OSError:
                pass


# ------------------------------------------------------------------ baselines
def baseline(key):
    return _read_json("baselines.json", {}).get(key)


def compare_and_learn(key, sig, dns_ms, alpha=0.25, enabled=True):
    """Differences between now and this network's baseline, then fold 'now' into the baseline."""
    with _lock:
        all_b = _read_json("baselines.json", {})
        b = all_b.get(key)
        changes = []
        if b:
            for field, label in (("gateways4", "gateway"), ("dns", "DNS servers"), ("suffix", "DNS suffix")):
                if sig.get(field) != b.get(field):
                    changes.append({"what": label, "before": b.get(field), "now": sig.get(field)})
            if bool(sig.get("v6")) != bool(b.get("v6")):
                changes.append({"what": "IPv6", "before": "available" if b.get("v6") else "unavailable",
                                "now": "available" if sig.get("v6") else "unavailable"})
            avg = b.get("dns_ms")
            if dns_ms is not None and avg and dns_ms > max(3 * avg, avg + 80):
                changes.append({"what": "DNS latency", "before": f"~{round(avg)} ms", "now": f"{round(dns_ms)} ms"})
        nb = dict(sig)
        nb["seen"] = (b or {}).get("seen", 0) + 1
        nb["first"] = (b or {}).get("first", time.time())
        nb["last"] = time.time()
        if dns_ms is not None:
            nb["dns_ms"] = dns_ms if not (b and b.get("dns_ms")) else (1 - alpha) * b["dns_ms"] + alpha * dns_ms
        elif b:
            nb["dns_ms"] = b.get("dns_ms")
        if enabled:
            all_b[key] = nb
            _write_json("baselines.json", all_b)
        return {"known": bool(b), "seen": nb["seen"], "changes": changes, "first": nb["first"]}


# ------------------------------------------------------------------ sinkhole clusters
def note_filtered(key, name, ips, enabled=True):
    if not enabled or not ips:
        return
    with _lock:
        d = _read_json("sinkholes.json", {})
        net = d.setdefault(key, {})
        for ip in ips:
            names = net.setdefault(ip, [])
            if name not in names:
                names.append(name)
                del names[:-50]
        _write_json("sinkholes.json", d)


def sinkholes(key):
    """Addresses that answered for at least one filtered name on this network."""
    return {ip: names for ip, names in _read_json("sinkholes.json", {}).get(key, {}).items() if names}
