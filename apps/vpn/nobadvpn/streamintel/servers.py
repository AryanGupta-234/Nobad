"""The user's real VPN locations, read from the running engine (never assumed): which country each server is in,
how sure we are, its latest measured latency, and what NOBAD has seen streaming services do through it.

Country evidence, strongest first:
  ip-geolocation  the endpoint IP was geolocated (engine geo cache, needs the 'IP lookup' privacy setting);
  name            the config name contains a country name or code ('usa', 'japan', 'de-fra') - an estimate;
  none            unknown: such a server is never matched to a country."""
import re
import time

from .availability import family

# Existing reachability checks (tools.SERVICES ids) that correspond to streaming platforms TMDB reports.
SERVICE_CHECK = {"netflix": "netflix", "amazon prime video": "prime", "amazon video": "prime", "prime video": "prime",
                 "disney plus": "disney", "disney+": "disney"}


def check_id_for(provider_name):
    f = family(provider_name or "").casefold().strip()
    return SERVICE_CHECK.get(f)


def _name_country(name, countries):
    raw = (name or "").casefold()
    tokens = [t for t in re.split(r"[^a-z]+", raw) if t]
    joined = "".join(tokens)
    for t in [joined] + tokens:                       # full names / aliases first: 'unitedkingdom', 'japan', 'usa'
        if len(t) >= 3:
            c = countries.code(t) or countries.city(t)  # then well-known server cities: 'frankfurt', 'NewYork'
            if c:
                return c
    for i in range(len(tokens) - 1):                  # two-word cities split by separators: 'new-york', 'hong_kong'
        c = countries.city(tokens[i] + tokens[i + 1])
        if c:
            return c
    # Then a 2-letter ISO code: the whole name ('us') or the first part of a location code ('de-fra', 'us-east-1').
    # Not when the rest is a generic word: 'my-vpn' is "my VPN", not Malaysia.
    if tokens and len(tokens[0]) == 2:
        code = tokens[0].upper() if countries.is_code(tokens[0]) else countries.code(tokens[0])   # 'uk' -> GB
        rest = [t for t in tokens[1:] if t not in GENERIC_NAME_WORDS]
        if code and (len(tokens) == 1 or (rest and len(rest) == len(tokens) - 1)):
            return code
    return None


GENERIC_NAME_WORDS = {"vpn", "wg", "wireguard", "server", "tunnel", "conf", "config", "home", "work", "office", "test",
                      "main", "backup", "new", "old", "personal", "private", "free", "pro", "net", "my", "our", "the"}


def inventory(tunnel, smart, countries, now=None):
    now = now or time.time()
    st_regions = getattr(tunnel, "_regions", []) or []
    geo, pings = getattr(tunnel, "geo", {}) or {}, getattr(tunnel, "pings", {}) or {}
    svc = ((smart.snapshot() if smart else {}) or {}).get("svc", {}) if smart else {}
    out = []
    for r in st_regions:
        name = r["name"]
        g = geo.get(r.get("host")) or {}
        code, basis = (g.get("country") or "").upper() or None, "ip-geolocation"
        if not code:
            code, basis = _name_country(name, countries), "name"
        if not code:
            basis = "none"
        p = pings.get(name) or {}
        rtt, loss = p.get("rtt"), p.get("loss")
        reach = "unknown" if not p else ("answering" if rtt is not None and (loss or 0) < 100 else "not answering")
        hist = {}
        for sid, rec in (svc.get(name) or {}).items():
            hist[sid] = {"ok": rec.get("ok", 0), "bad": rec.get("bad", 0), "last": rec.get("last"),
                         "blocked_now": (rec.get("blocked_until") or 0) > now}
        out.append({"name": name, "country": code, "country_basis": basis, "city": g.get("city"),
                    "country_name": countries.name(code) if code else None,
                    "rtt": rtt, "loss": loss, "rtt_estimated": bool(p.get("est")), "reach": reach,
                    "active": getattr(tunnel, "active", None) == name and bool(getattr(tunnel, "connected", False)),
                    "service_history": hist, "favorite": False})
    return out
