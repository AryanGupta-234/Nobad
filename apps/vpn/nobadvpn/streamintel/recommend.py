"""Which of the user's VPN locations best matches the catalogues that list a title, and why.

A country is only ever recommended when (1) the availability source lists the title there, (2) the user has a
server whose country we know, and (3) no documented restriction for this title exists there. Every score comes
with its reasons and caveats, so the UI can explain it. Server load is not reported by WireGuard configs, so it is
stated as unknown instead of being guessed. Nothing here guarantees playback or that a service won't detect the VPN."""
from .availability import OFFER_RANK, matches_services
from .servers import check_id_for

OFFER_WEIGHT = {"subscription": 1.0, "free": 0.95, "free with ads": 0.9, "rent": 0.55, "buy": 0.45}


def _latency_points(s):
    if s["rtt"] is None:
        return 6, "no recent latency measurement"
    rtt = s["rtt"]
    pts = 20 if rtt < 60 else 16 if rtt < 120 else 11 if rtt < 200 else 6 if rtt < 300 else 2
    return pts, f"{rtt} ms latency{' (estimated over TCP)' if s['rtt_estimated'] else ''}"


def recommend(av, servers, restrictions_doc, my_services=(), home_country=None, offer_filter=None):
    providers = av["providers"]
    by_country = {}
    for s in servers:
        if s["country"]:
            by_country.setdefault(s["country"], []).append(s)
    banned = {}
    for r in (restrictions_doc or {}).get("records", []):
        if r.get("code") and "later lifted" not in r.get("tags", []):
            banned.setdefault(r["code"], []).append(r)
    restrictions_known = bool(restrictions_doc and restrictions_doc.get("status") == "ok")

    options, listed_no_server = [], []
    for c in av["listed"]:
        types = [t for t in c["offers"] if not offer_filter or t in offer_filter]
        if not types:
            continue
        srv = by_country.get(c["code"], [])
        if not srv:
            listed_no_server.append({"code": c["code"], "name": c["name"], "best": c["best"]})
            continue
        best_type = min(types, key=lambda t: OFFER_RANK.get(t, 99))
        mine = matches_services(c, my_services, providers)
        reasons, caveats = [], []
        score = 45 * OFFER_WEIGHT.get(best_type, 0.4)
        n_prov = len({p for t in types for p in c["offers"][t]})
        reasons.append(f"Listed for {best_type} in {c['name']}" + (f" on {n_prov} platforms" if n_prov > 1 else ""))
        if my_services:
            if mine:
                score += 12
                reasons.append("On a service you said you have")
            else:
                score -= 15
                caveats.append("Not on any service you said you have")
        best_srv, best_pts, best_note = None, float("-inf"), ""
        for s in srv:
            pts, note = _latency_points(s)
            if s["reach"] == "not answering":
                pts -= 30
            if pts > best_pts:
                best_srv, best_pts, best_note = s, pts, note
        score += best_pts                       # negative for a server that didn't answer: it must not win
        reasons.append(f"Your server '{best_srv['name']}' is in {c['name']} ({best_note})")
        if best_srv["reach"] == "not answering":
            caveats.append(f"'{best_srv['name']}' didn't answer the last probe")
        if best_srv["country_basis"] == "name":
            score -= 8
            caveats.append("Server country is estimated from its name; turn on IP lookup to verify it")
        else:
            score += 6
        # what NOBAD has seen the platforms do through this server
        checked = set()
        for t in types:
            for pid in c["offers"][t]:
                p = next((x for x in providers if x["id"] == pid), None)
                cid = check_id_for(p["name"] if p else "")
                if not cid or cid in checked:
                    continue
                checked.add(cid)
                h = best_srv["service_history"].get(cid)
                if not h:
                    continue
                if h["blocked_now"] or (h["bad"] > h["ok"]):
                    score -= 12
                    caveats.append(f"{p['family']} recently looked blocked or VPN-detected through this server")
                elif h["ok"]:
                    score += 5
                    reasons.append(f"{p['family']} answered normally through this server before")
        if not av["fresh"]:
            score -= 10
            caveats.append("Availability data is older than 12 hours")
        if c["code"] in banned:
            caveats.append(f"Documented restriction for this title in {c['name']}: see Restrictions")
            score -= 40
        if not restrictions_known:
            caveats.append("Restriction records couldn't be checked")
        caveats.append("Server load isn't reported by your provider")
        options.append({"code": c["code"], "name": c["name"], "server": best_srv["name"],
                        "other_servers": [s["name"] for s in srv if s is not best_srv],
                        "offer": best_type, "score": max(0, min(100, round(score))), "reasons": reasons,
                        "caveats": caveats, "restricted": c["code"] in banned,
                        "verify_services": sorted(checked)})
    options.sort(key=lambda o: (o["restricted"], -o["score"]))
    home = None
    if home_country:
        home_listed = next((c for c in av["listed"] if c["code"] == home_country), None)
        home = {"code": home_country, "listed": bool(home_listed),
                "best": home_listed["best"] if home_listed else None}
    if not av["listed"]:
        verdict = "not-listed-anywhere"
    elif options and not options[0]["restricted"]:
        verdict = "recommend"
    elif options:
        verdict = "only-restricted"
    else:
        verdict = "no-matching-server"
    return {"verdict": verdict, "options": options[:12], "listed_without_server": listed_no_server,
            "home": home, "servers_known": sum(1 for s in servers if s["country"]),
            "servers_unknown": [s["name"] for s in servers if not s["country"]],
            "disclaimer": "A listing and a matching server don't guarantee playback: services may detect VPNs, and "
                          "using a VPN doesn't change which local laws apply to you."}
