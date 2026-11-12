"""POST /api/si_* handlers. Searching is quick and answered directly; a title report is built on a worker thread and
pushed as 'si_title', then 'si_restrictions' when the (slower, cached weekly) restriction lookup finishes.
Connecting uses the existing /api/connect; this module never touches the tunnel."""
import re
import threading

from ..ctx import ctx
from ..logbus import broadcast, log
from ..syscmd import run_once
from . import net
from .service import NoKey, StreamIntel

_lock = threading.Lock()
_si = None
_KEY = re.compile(r"(movie|tv):(\d{1,10})")


def get():
    global _si
    with _lock:
        if _si is None:
            _si = StreamIntel()
        return _si


def _err(e):
    if isinstance(e, NoKey):
        return {"ok": False, "error": "Add your free TMDB API key first.", "code": "no-key"}
    if isinstance(e, net.SourceError):
        msg = {"auth": "TMDB rejected the saved key. Check it in Settings.",
               "rate": "TMDB is rate-limiting requests. Try again in a minute.",
               "unavailable": "Couldn't reach TMDB.", "notfound": "TMDB doesn't know this title."}.get(e.kind, f"TMDB error: {e}")
        return {"ok": False, "error": msg, "code": e.kind}
    log(f"streaming intelligence: {type(e).__name__}: {e}", "warn")
    return {"ok": False, "error": "Something went wrong while reading streaming data.", "code": "internal"}


def h_status(b):
    st = get().status()
    st.update({"ok": True, "my_services": ctx.settings.get("si_my_services") or [],
               "language": ctx.settings.get("si_language") or "en-US"})
    return st


def h_key(b):
    return get().set_key(str(b.get("key") or ""), ctx.settings.get("si_language") or "en-US")


def h_key_clear(b):
    return get().clear_key()


def h_search(b):
    try:
        return get().search(str(b.get("q") or ""), ctx.settings.get("si_language") or "en-US")
    except Exception as e:
        return _err(e)


def h_title(b):
    m = _KEY.fullmatch(str(b.get("key") or ""))
    if not m:
        return {"ok": False, "error": "bad title"}
    kind, tid, force = m.group(1), int(m.group(2)), bool(b.get("force"))
    si = get()
    if not si.cred.get():
        return _err(NoKey())

    def work():
        try:
            rep = si.report(kind, tid, ctx.tunnel, ctx.smart, ctx.settings, force=force)
        except Exception as e:
            broadcast("si_title", dict(_err(e), key=f"{kind}:{tid}"))
            return
        broadcast("si_title", rep)
        try:
            doc, rec = si.with_restrictions(rep, ctx.tunnel, ctx.smart, ctx.settings)
        except Exception as e:
            log(f"streaming intelligence: restriction lookup failed: {e}", "warn")
            doc, rec = {"status": "unavailable", "records": [], "error": str(e)}, rep["recommendation"]
        broadcast("si_restrictions", {"key": rep["key"], "restrictions": doc, "recommendation": rec})
    return {"ok": True} if run_once("si_title", work) else {"ok": False, "error": "Already loading a title."}


def h_providers(b):
    region = str(b.get("region") or "").upper()
    if region and not re.fullmatch(r"[A-Z]{2}", region):
        return {"ok": False, "error": "bad region"}
    try:
        return {"ok": True, "providers": get().provider_catalog(region or None, ctx.settings.get("si_language") or "en-US")}
    except Exception as e:
        return _err(e)


def h_prefs(b):
    svc = b.get("my_services")
    if not isinstance(svc, list) or len(svc) > 200 or not all(isinstance(x, int) and 0 < x < 10**7 for x in svc):
        return {"ok": False, "error": "bad services list"}
    ctx.settings.set("si_my_services", sorted(set(svc)))
    return {"ok": True}


def h_verify(b):
    """After the user connected to a recommended region: does the exit really sit in that country, and do the
    platforms NOBAD can check answer normally from it? Uses the existing exit-IP lookup and service checks."""
    want = str(b.get("country") or "").upper()
    sids = [s for s in (b.get("services") or []) if isinstance(s, str) and re.fullmatch(r"[a-z]{2,20}", s)][:4]
    if not re.fullmatch(r"[A-Z]{2}", want):
        return {"ok": False, "error": "bad country"}

    def work():
        from .. import tools
        t = ctx.tunnel
        res = {"country": want, "connected": bool(t.connected), "server": t.active if t.connected else None}
        if t.connected:
            tools.fetch_ipinfo()
            ex = t.exit or {}
            got = (ex.get("country") or "").upper() or None
            res["exit_country"] = got
            res["exit_lookup"] = "disabled" if ex.get("disabled") else ("error" if ex.get("error") else "ok")
            res["country_match"] = (got == want) if got else None
            res["services"] = [x for x in (tools.check_one_service(s) for s in sids) if x]
        broadcast("si_verify", res)
    return {"ok": True} if run_once("si_verify", work) else {"ok": False, "error": "A check is already running."}


TRUSTED_HOSTS = {"www.themoviedb.org", "themoviedb.org", "www.imdb.com", "imdb.com", "en.wikipedia.org",
                 "www.wikidata.org", "www.justwatch.com"}


def h_open(b):
    """Open a link from the data (TMDB page, watch link, Wikipedia section, citation) in the browser. http(s) only, no
    credentials; hosts outside TRUSTED_HOSTS need confirm=true (the UI asks the user first, showing the host)."""
    from urllib.parse import urlsplit
    from ..syscmd import open_url_as_user
    url = str(b.get("url") or "")[:2000]
    try:
        u = urlsplit(url)
    except ValueError:
        return {"ok": False, "error": "bad link"}
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        return {"ok": False, "error": "bad link"}
    if u.hostname.lower() not in TRUSTED_HOSTS and not b.get("confirm"):
        return {"ok": False, "error": "confirm", "host": u.hostname}
    return {"ok": True} if open_url_as_user(url) else {"ok": False, "error": "couldn't open that link"}


def h_cache_clear(b):
    return get().clear_cache()


HANDLERS = {"si_status": h_status, "si_key": h_key, "si_key_clear": h_key_clear, "si_search": h_search,
            "si_title": h_title, "si_providers": h_providers, "si_prefs": h_prefs, "si_verify": h_verify, "si_open": h_open,
            "si_cache_clear": h_cache_clear}
