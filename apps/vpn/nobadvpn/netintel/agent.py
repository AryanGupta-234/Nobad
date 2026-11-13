"""Smart fix agent: makes a site that the network's DNS filters reachable again, without breaking anything else.

Authorisation: nothing is changed unless the user clicks "Fix" on an investigation, or has switched the agent on
(setting `ni_autofix`, off by default). That switch is the standing permission for the autonomous mode.

How a fix works (each step is real and logged):
 1. preflight - refuse when a DNS change can't help or could break things: site also SNI/IP-filtered, DNS intercepted on
    the path, VPN connected, work/school domain or NRPT policy, a network-provided DNS suffix (local names), captive portal.
 2. plan      - independent resolvers that returned the real address for the site, fastest first (IPv6 only if the
    adapter has IPv6), taken from the investigation's own measurements.
 3. canaries  - names this PC really uses (Windows DNS cache) that resolve fine right now.
 4. apply     - original DNS written to the change journal FIRST, then Set-DnsClientServerAddress on that adapter.
 5. verify    - the site resolves to its real address, every canary still resolves, the router still answers.
               Any regression -> automatic rollback from the journal.
A fix belongs to the network it was made on: leaving that network restores the original DNS, coming back
re-applies it (same checks) when the agent is on."""
import json
import os
import threading
import time

from .. import netjournal
from ..logbus import log
from ..syscmd import ping_stats, run
from . import dnsintel, history, investigate, probes, system

PROFILES = os.path.join(history.NI_DIR, "fix_profiles.json")
SCAN_EVERY = 30 * 60          # autonomous DNS-cache scan: every 30 min while the app runs (one PowerShell call)
LOCAL_TLDS = (".local", ".lan", ".home", ".internal", ".intranet", ".corp", ".home.arpa", ".arpa", ".localdomain")


def _ps(script, timeout=40, runner=None):
    return (runner or run)(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def dns_cache_entries(runner=None):
    """[{name, type, data}] from the Windows DNS client cache: what this PC has really been looking up."""
    r = _ps("Get-DnsClientCache | Select-Object Entry,Type,Data | ConvertTo-Json -Compress", runner=runner)
    try:
        d = json.loads((r.stdout or "").strip() or "[]")
    except ValueError:
        return []
    d = d if isinstance(d, list) else [d]
    tmap = {1: "A", 5: "CNAME", 28: "AAAA"}
    return [{"name": str(x.get("Entry") or "").lower().rstrip("."), "type": tmap.get(x.get("Type"), str(x.get("Type"))),
             "data": str(x.get("Data") or "").lower().rstrip(".")} for x in d if x and x.get("Entry")]


def canary_names(entries, exclude=(), suffix="", limit=10):
    out = []
    for e in entries:
        n = e["name"]
        if e["type"] not in ("A", "AAAA") or "." not in n or n in out or n in exclude:
            continue
        if n.endswith(LOCAL_TLDS) or (suffix and n.endswith("." + suffix.lower())) or n == "localhost":
            continue
        out.append(n)
        if len(out) >= limit:
            break
    return out


def preflight(inv, snap, tunnel=None, captive=None, manual=False):
    """(ok, reasons). Reasons explain every refusal in plain words."""
    why = []
    kinds = {f["kind"] for f in inv.get("findings", [])}
    filt = [f for f in inv.get("findings", []) if f["kind"] == "dns-filtering" and f["confidence"] >= (0.55 if manual else 0.8)]
    fail = [f for f in inv.get("findings", []) if f["kind"] in ("resolver-failed", "resolver-error")]
    if not filt and not fail:
        why.append("the investigation did not find (confident) DNS filtering or a failing resolver")
    if inv.get("affected") is False:
        why.append("Windows already gets the real address for this site")
    for k, msg in (("sni-filtering", "the site is also filtered by name (SNI): a DNS change can't unblock it"),
                   ("ip-unreachable", "the site's real addresses are unreachable from this network: a DNS change can't help"),
                   ("dns-interception", "this network intercepts plain DNS, so a DNS setting would be overridden on the path")):
        if k in kinds:
            why.append(msg)
    if tunnel is not None and getattr(tunnel, "connected", False):
        why.append("NOBAD is connected: the tunnel's DNS is in use, nothing to fix on the network side")
    if snap.get("domain_joined"):
        why.append("this PC belongs to a work/school domain, whose DNS must not be replaced")
    if snap.get("nrpt_rules"):
        why.append("Windows has DNS policy rules (NRPT) that a manual DNS change could conflict with")
    a = system.adapter(snap, snap.get("primary")) or {}
    if not a:
        why.append("no active network adapter")
    if a.get("suffix") or a.get("dhcp_domain"):
        why.append(f"the network provides local names (suffix '{a.get('suffix') or a.get('dhcp_domain')}') that only its own DNS knows")
    if captive and captive.get("status") == "captive":
        why.append("a captive portal (sign-in page) is active on this network")
    return (not why), why


def plan(inv, snap):
    """Independent resolvers that answered the site with the consensus addresses, fastest first."""
    cons = set(inv.get("data", {}).get("consensus", {}).get("addrs", []))
    a = system.adapter(snap, snap.get("primary")) or {}
    v6_ok = bool(a.get("global_v6"))
    good = []
    for m in inv.get("data", {}).get("matrix", []):
        if m.get("group") != "reference" or not m.get("ip"):
            continue
        x = m["results"].get("A") or {}
        if x.get("rcode") == "NOERROR" and set(x.get("addrs") or []) & cons:
            good.append((x.get("rtt_ms") or 9e9, m["ip"]))
    good.sort()
    v4 = [ip for _, ip in good if ":" not in ip][:2]
    v6 = [ip for _, ip in good if ":" in ip][:2] if v6_ok else []
    return {"adapter_index": a.get("index"), "adapter": a.get("name"), "servers": v4 + v6, "v4": v4, "v6": v6}


class FixAgent:
    def __init__(self, settings, tunnel=None, notify=None, runner=None):
        self.settings, self.tunnel, self.notify, self.runner = settings, tunnel, notify, runner
        self.lock = threading.Lock()
        self.last = None
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------ one fix
    def fix(self, inv, manual=True, snap=None):
        """Returns a result dict; never raises for network problems."""
        if not self.lock.acquire(blocking=False):
            return {"ok": False, "state": "busy", "reasons": ["another fix is running"]}
        try:
            return self._fix(inv, manual, snap)
        finally:
            self.lock.release()

    def _fix(self, inv, manual, snap):
        t0 = time.time()
        name = inv.get("target")
        snap = snap or system.snapshot(None)
        if "error" in snap:
            return self._result(name, False, "refused", [snap["error"]])
        from .. import netinfo
        captive = netinfo.captive_check(timeout=3)
        ok, why = preflight(inv, snap, self.tunnel, captive, manual)
        if not ok:
            return self._result(name, False, "refused", why)
        p = plan(inv, snap)
        if not p["v4"]:
            return self._result(name, False, "refused", ["no independent IPv4 resolver returned the real address"])
        idx = p["adapter_index"]
        before = netjournal.dns_snapshot(idx)
        if not before:
            return self._result(name, False, "refused", ["could not read the adapter's current DNS settings"])
        cache = dns_cache_entries(self.runner)
        canaries = canary_names(cache, exclude=(name,), suffix=(system.adapter(snap, idx) or {}).get("suffix", ""))
        base = {n: probes.os_resolve(n, timeout=4).get("ok") for n in canaries}
        base_ok = [n for n, v in base.items() if v]
        gw = ((system.adapter(snap, idx) or {}).get("gateways4") or [None])[0]
        gw_before = ping_stats(gw, count=2, timeout_ms=800)["loss"] < 100 if gw else None
        key = history.network_key(snap)
        reason = f"{'Auto-fix' if not manual else 'Fix'}: {name} was filtered by the network's DNS"
        eid = netjournal.record("dns", p["adapter"], before, {"servers": p["servers"]}, reason,
                                network=key, site=name, auto=not manual)
        servers = "@(" + ",".join(f"'{s}'" for s in p["servers"]) + ")"
        r = _ps(f"$ErrorActionPreference='Stop';Set-DnsClientServerAddress -InterfaceIndex {int(idx)} -ServerAddresses {servers};"
                "Clear-DnsClientCache", runner=self.runner)
        if r.returncode != 0:
            e = next((x for x in netjournal.entries() if x.get("id") == eid), None)
            if e:
                netjournal.restore_entry(e)    # in case Windows applied part of it
            netjournal.forget(eid)
            return self._result(name, False, "failed", [f"Windows refused the change: {(r.stderr or '').strip()[:160]}"])
        netjournal.mark(eid, "applied")
        time.sleep(1.0)
        # ---- verify: the site, the canaries, the router
        checks, bad = [], []
        cons = set(inv.get("data", {}).get("consensus", {}).get("addrs", []))
        got = probes.os_resolve(name, timeout=5)
        site_ok = bool(got.get("ok") and set(got.get("ips", [])) & cons)
        checks.append({"check": f"{name} resolves to its real address", "ok": site_ok,
                       "detail": ", ".join(got.get("ips", [])[:3]) or got.get("error")})
        if not site_ok:
            bad.append(f"{name} still does not resolve to its real address")
        for n in base_ok:
            v = probes.os_resolve(n, timeout=5)
            checks.append({"check": f"{n} still resolves", "ok": bool(v.get("ok")), "detail": v.get("error")})
            if not v.get("ok"):
                bad.append(f"{n} stopped resolving")
        if gw and gw_before:
            gw_now = ping_stats(gw, count=2, timeout_ms=800)["loss"] < 100
            checks.append({"check": f"router {gw} still answers", "ok": gw_now})
            if not gw_now:
                bad.append(f"the router {gw} stopped answering")
        if bad:
            e = next((x for x in netjournal.entries() if x.get("id") == eid), None)
            rb_ok, rb = netjournal.restore_entry(e) if e else (False, "journal entry missing")
            if rb_ok:
                netjournal.forget(eid)
            log(f"DNS fix for {name} rolled back: {'; '.join(bad)}", "warn")
            return self._result(name, False, "rolled_back", bad, checks=checks, rollback=rb, took=time.time() - t0)
        self._save_profile(key, {"servers": p["servers"], "adapter": p["adapter"], "target": name, "ts": time.time()})
        log(f"DNS fix applied on {p['adapter']}: {', '.join(p['servers'])} ({len(base_ok)} other names verified)", "ok")
        if self.notify:
            self.notify("Site unblocked", f"{name} now resolves correctly. NOBAD checked {len(base_ok)} other sites; "
                        "any reset puts your DNS back.", "netintel", "ok")
        return self._result(name, True, "applied", [], checks=checks, servers=p["servers"], adapter=p["adapter"],
                            entry=eid, took=time.time() - t0)

    def _result(self, target, ok, state, reasons, **extra):
        self.last = {"target": target, "ok": ok, "state": state, "reasons": reasons, "ts": time.time(), **extra}
        history.append("fix", {"target": target, "state": state, "reasons": reasons[:4]},
                       enabled=bool(self.settings.get("ni_history")))
        return self.last

    def rollback(self, entry_id):
        e = next((x for x in netjournal.entries() if x.get("id") == entry_id), None)
        if not e:
            return {"ok": False, "error": "no such change"}
        ok, detail = netjournal.restore_entry(e)
        if ok:
            netjournal.forget(entry_id)
            self._drop_profile(e.get("network"))
        return {"ok": ok, "detail": detail}

    # ------------------------------------------------------------------ per-network profiles
    def _profiles(self):
        try:
            with open(PROFILES, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_profile(self, key, prof):
        d = self._profiles()
        d[key] = prof
        os.makedirs(os.path.dirname(PROFILES), exist_ok=True)
        with open(PROFILES + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(PROFILES + ".tmp", PROFILES)

    def _drop_profile(self, key):
        d = self._profiles()
        if key in d:
            del d[key]
            with open(PROFILES + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(PROFILES + ".tmp", PROFILES)

    def on_network_change(self):
        """A fix is only valid on the network it was made for (hotel Wi-Fi must keep its own DNS)."""
        if not netjournal.entries() and not (self.settings.get("ni_autofix") and self._profiles()):
            return           # nothing to look after: costs nothing
        snap = system.snapshot(None)
        if "error" in snap:
            return
        key = history.network_key(snap)
        for e in netjournal.entries():
            if e.get("kind") == "dns" and e.get("network") and e["network"] != key and e.get("state") == "applied":
                ok, detail = netjournal.restore_entry(e)
                if ok:
                    netjournal.forget(e["id"])
                    log(f"left the network a DNS fix was made for: original DNS restored on {e.get('target')}", "info")
        if self.settings.get("ni_autofix") and key in self._profiles() and not any(
                e.get("network") == key for e in netjournal.entries()):
            prof = self._profiles()[key]
            try:
                inv = investigate.investigate_site(prof["target"], self.settings, self.tunnel, snap=snap)
                self.fix(inv, manual=False, snap=snap)
            except Exception as ex:
                log(f"re-applying the DNS fix failed: {ex}", "warn")

    # ------------------------------------------------------------------ autonomous mode
    def scan_once(self):
        """Look in the DNS cache for answers that look like DNS policy rewrites; investigate the first one."""
        if not self.settings.get("ni_autofix"):
            return None
        snap = system.snapshot(None)
        if "error" in snap:
            return None
        sinks = set(history.sinkholes(history.network_key(snap)))
        cands = []
        for e in dns_cache_entries(self.runner):
            if e["type"] == "CNAME" and dnsintel.policy_words_in(e["data"]) and dnsintel.registrable(e["data"]) != dnsintel.registrable(e["name"]):
                cands.append(e["name"])
            elif e["type"] in ("A", "AAAA") and e["data"] in sinks:
                cands.append(e["name"])
        for name in dict.fromkeys(cands):
            try:
                inv = investigate.investigate_site(name, self.settings, self.tunnel, snap=snap)
            except ValueError:
                continue
            if inv.get("verdict") == "dns-filtering" and inv.get("affected") is not False:
                return self.fix(inv, manual=False, snap=snap)
        return None

    def start(self):
        if self._thread:
            return
        def loop():
            while not self._stop.wait(SCAN_EVERY):
                try:
                    self.scan_once()
                except Exception as ex:
                    log(f"fix agent scan failed: {ex}", "warn")
        self._thread = threading.Thread(target=loop, daemon=True, name="ni-agent")
        self._thread.start()

    def stop(self):
        self._stop.set()
