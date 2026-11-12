"""Country-by-country availability from TMDB's watch-provider data (sourced from JustWatch).

Three states are kept strictly apart:
  listed      the source reports at least one offer in that country right now (as of `fetched`);
  not_listed  the source covers that country, but reports no offer;
  unknown     the source doesn't cover that country at all, so nothing can be said.
Nothing here is ever 'confirmed': catalogues change daily, and a listing doesn't guarantee playback."""
import re

# TMDB offer keys -> user-facing offer types, best first. 'free' isn't in TMDB's schema docs but is returned in
# practice; unknown future keys are kept as-is instead of being dropped.
OFFER_TYPES = [("flatrate", "subscription"), ("free", "free"), ("ads", "free with ads"), ("rent", "rent"), ("buy", "buy")]
OFFER_RANK = {t: i for i, (_k, t) in enumerate(OFFER_TYPES)}
_FAMILY_SUFFIX = re.compile(r"\s+(standard|basic|premium)?\s*with\s+ads$|\s+(basic|standard|premium)$", re.I)


def family(name):
    """'Netflix Standard with Ads' -> 'Netflix'. Channels sold through another store keep their own name."""
    return _FAMILY_SUFFIX.sub("", (name or "").strip()) or name


def build(watch, covered, countries, fetched, fresh=True):
    """watch: TMDB 'watch/providers' object ({'results': {CC: {...}}}); covered: country codes the source covers."""
    results = (watch or {}).get("results") or {}
    listed, providers = [], {}
    for cc, entry in results.items():
        cc = cc.upper()
        offers = {}
        for k, v in entry.items():
            if k == "link" or not isinstance(v, list):
                continue
            label = dict(OFFER_TYPES).get(k, k)
            seen = set()
            for p in sorted(v, key=lambda x: x.get("display_priority", 999)):
                try:
                    pid = int(p.get("provider_id"))      # remote data: an id is a number, nothing else reaches the UI
                except (TypeError, ValueError):
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                offers.setdefault(label, []).append(pid)
                pr = providers.setdefault(pid, {"id": pid, "name": p.get("provider_name"), "family": family(p.get("provider_name")),
                                                "logo": (p.get("logo_path") or "").lstrip("/") or None, "countries": {}})
                pr["countries"].setdefault(cc, []).append(label)
        if not offers:
            continue
        best = min(offers, key=lambda t: OFFER_RANK.get(t, 99))
        listed.append({"code": cc, "name": countries.name(cc), "offers": offers, "best": best,
                       "link": entry.get("link")})
    listed.sort(key=lambda c: (OFFER_RANK.get(c["best"], 99), -sum(len(v) for v in c["offers"].values()), c["name"] or ""))
    have = {c["code"] for c in listed}
    covered = {c.upper() for c in covered or []}
    not_listed = sorted((c for c in covered if c not in have), key=lambda c: countries.name(c) or c)
    return {
        "listed": listed,
        "not_listed": [{"code": c, "name": countries.name(c)} for c in not_listed],
        "coverage": len(covered), "unknown_note": "Countries outside the source's coverage are unknown, not unavailable.",
        "providers": sorted(providers.values(), key=lambda p: (-len(p["countries"]), p["name"] or "")),
        "fetched": fetched, "fresh": fresh,
        "source": "JustWatch via TMDB",
    }


def state_for(av, code):
    code = (code or "").upper()
    for c in av["listed"]:
        if c["code"] == code:
            return "listed", c
    if any(c["code"] == code for c in av["not_listed"]):
        return "not_listed", None
    return "unknown", None


def matches_services(country, my_services, providers):
    """Subscription/free offers in that country from services the user said they have (empty = no filter)."""
    if not my_services:
        return None
    mine = {int(x) for x in my_services}
    fams = {p["family"] for p in providers if p["id"] in mine}
    hits = []
    for t in ("subscription", "free", "free with ads"):
        for pid in country["offers"].get(t, []):
            p = next((x for x in providers if x["id"] == pid), None)
            if pid in mine or (p and p["family"] in fams):
                hits.append(pid)
    return hits
