"""POST /api/ni_* handlers for the Network Intelligence section. Long work runs on a worker thread (run_once) and
its result is pushed to the UI as an event; quick reads return directly."""
import itertools
import time

from ..ctx import ctx
from ..logbus import broadcast, log
from ..syscmd import run_once
from . import dnswire, history, investigate, system

_CACHE = {}          # investigation id -> result (the fix agent acts on a measured investigation, never on input)
_ids = itertools.count(1)


def _busy(what):
    return {"ok": False, "error": f"{what} is already running."}


def _agent():
    return getattr(ctx, "niagent", None)


def h_overview(b):
    def work():
        broadcast("ni_overview", investigate.overview(ctx.settings, ctx.tunnel))
    return {"ok": True} if run_once("ni_overview", work) else _busy("A network overview")


def h_investigate(b):
    try:
        name = investigate.normalize_target(b.get("target"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    def work():
        broadcast("ni_progress", {"target": name, "stage": "measuring"})
        res = investigate.investigate_site(name, ctx.settings, ctx.tunnel, getattr(ctx.tunnel, "home", None),
                                           getattr(ctx.tunnel, "exit", None))
        res["id"] = str(next(_ids))
        _CACHE[res["id"]] = res
        for k in sorted(_CACHE, key=int)[:-10]:
            _CACHE.pop(k, None)
        res["fixable"] = _fixable(res)
        broadcast("ni_investigation", res)
        a = _agent()
        if a and ctx.settings.get("ni_autofix") and res.get("verdict") == "dns-filtering" and res.get("affected") is not False:
            broadcast("ni_fix", a.fix(res, manual=False))
    return {"ok": True, "target": name} if run_once("ni_investigate", work) else _busy("An investigation")


def _fixable(res):
    from .agent import preflight
    snap = system.snapshot(None)
    ok, why = preflight(res, snap, ctx.tunnel, None, manual=True) if "error" not in snap else (False, [snap["error"]])
    return {"ok": ok, "reasons": why}


def h_lookup(b):
    try:
        name = investigate.normalize_target(b.get("name"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    types = [t for t in (b.get("types") or ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA"]) if t in dnswire.TYPES][:7]
    if not types:
        return {"ok": False, "error": "choose at least one record type"}

    def work():
        from .dnsintel import lookup
        snap = system.snapshot(ctx.tunnel.active if ctx.tunnel and ctx.tunnel.connected else None)
        rs = investigate.resolver_set(snap, ctx.settings) if "error" not in snap else []
        broadcast("ni_lookup", {"name": name, "types": types, "rows": lookup(name, types, rs), "ts": time.time()})
    return {"ok": True} if run_once("ni_lookup", work) else _busy("A DNS lookup")


def h_vpn(b):
    def work():
        broadcast("ni_vpn", investigate.vpn_integrity(ctx.settings, ctx.tunnel, ctx.netwatch))
    return {"ok": True} if run_once("ni_vpn", work) else _busy("A VPN integrity check")


def h_history(b):
    return {"ok": True, "items": history.recent(80), "enabled": bool(ctx.settings.get("ni_history"))}


def h_history_clear(b):
    history.clear()
    log("Network Intelligence history cleared", "info")
    return {"ok": True}


def h_fix(b):
    a = _agent()
    inv = _CACHE.get(str(b.get("id")))
    if not a or not inv:
        return {"ok": False, "error": "Run the investigation again first (results expire)."}

    def work():
        broadcast("ni_fix", a.fix(inv, manual=True))
    return {"ok": True} if run_once("ni_fix", work) else _busy("A fix")


def h_rollback(b):
    a = _agent()
    if not a:
        return {"ok": False, "error": "agent unavailable"}
    r = a.rollback(str(b.get("entry") or ""))
    broadcast("ni_fix", {"state": "rolled_back_by_user", "ok": r.get("ok"), "reasons": [r.get("detail") or r.get("error")]})
    return r


HANDLERS = {"ni_overview": h_overview, "ni_investigate": h_investigate, "ni_lookup": h_lookup, "ni_vpn": h_vpn,
            "ni_history": h_history, "ni_history_clear": h_history_clear, "ni_fix": h_fix, "ni_rollback": h_rollback}
