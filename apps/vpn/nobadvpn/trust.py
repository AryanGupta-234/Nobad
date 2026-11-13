"""Trusted-network decisions (#15). A name alone is not enough: anyone can broadcast a Wi-Fi network called
"Home", and every wired network is called "Ethernet". A trusted network also has a recorded fingerprint:

* Wi-Fi: the security type and the access points (BSSIDs) the user confirmed, when Windows shows them (it hides
  them without Location permission), and the router's MAC address. Open Wi-Fi is never trusted.
* Wired: the router's MAC address.

Anything that doesn't match is "unverified": treated exactly like an untrusted network (more protection, never
less) until the user confirms it in Settings. Pure functions, so they are easy to test."""
from .netinfo import OPEN_AUTH, UNKNOWN_WIFI, norm_mac

MAX_BSSIDS = 16      # mesh / multi-band routers have several
MAX_GW = 4


def is_open(auth):
    return auth is not None and auth.strip().lower() in OPEN_AUTH


def _merge(old, new, cap):
    return ([x for x in (old or []) if x != new] + [new])[-cap:]


def check(ident, names, prints):
    """-> (state, why). state: 'trusted' | 'untrusted' | 'unverified'."""
    if not ident or not ident.get("name"):
        return "untrusted", "no network"
    name = ident["name"]
    if name == UNKNOWN_WIFI or name not in (names or []):
        return "untrusted", "not in the trusted list"
    fp = (prints or {}).get(name)
    if not fp:
        return "unverified", "trusted by name only; confirm it once so NOBAD can recognise it"
    if fp.get("kind") != ident.get("kind"):
        return "unverified", "a different kind of network uses this name"
    gw = norm_mac(ident.get("gw_mac"))
    if ident["kind"] == "wifi":
        auth, bssid = ident.get("auth"), norm_mac(ident.get("bssid"))
        if is_open(auth):
            return "untrusted", "open Wi-Fi (no password) is never trusted"
        if auth and fp.get("auth") and auth.lower() != fp["auth"].lower():
            return "unverified", f"its security changed ({fp['auth']} → {auth})"
        if bssid and fp.get("bssids"):
            if bssid in fp["bssids"]:
                return "trusted", ""
            return "unverified", "seen from an access point you haven't confirmed"
    if not gw:
        return "unverified", "couldn't identify the router"
    if gw in (fp.get("gw_macs") or []):
        return "trusted", ""
    return "unverified", "a different router uses this name"


def record(ident, prints):
    """Return (ok, new prints | error): add the current network's fingerprint (merging access points/routers)."""
    if not ident or not ident.get("name"):
        return False, "No network detected."
    name = ident["name"]
    if name == UNKNOWN_WIFI:
        return False, "Windows is hiding this Wi-Fi's name, so it can't be trusted."
    out = {k: dict(v) for k, v in (prints or {}).items()}
    old = out.get(name) if (out.get(name) or {}).get("kind") == ident.get("kind") else {}
    gw = norm_mac(ident.get("gw_mac"))
    if ident["kind"] == "wifi":
        auth, bssid = ident.get("auth"), norm_mac(ident.get("bssid"))
        if is_open(auth):
            return False, "Open Wi-Fi (no password) can't be trusted: anyone nearby can copy it."
        if not (auth and bssid) and not gw:
            return False, "Couldn't identify this Wi-Fi network (its access point or router), so it can't be trusted."
        same_auth = not (auth and old.get("auth")) or auth.lower() == old["auth"].lower()
        fp = {"kind": "wifi"}
        if auth and bssid:
            fp["auth"] = auth
            fp["bssids"] = _merge(old.get("bssids") if same_auth else [], bssid, MAX_BSSIDS)
        elif same_auth and old.get("auth") and old.get("bssids"):
            fp["auth"], fp["bssids"] = old["auth"], list(old["bssids"])
        if gw or old.get("gw_macs"):
            fp["gw_macs"] = _merge(old.get("gw_macs") if same_auth else [], gw, MAX_GW) if gw else list(old["gw_macs"])
        out[name] = fp
    else:
        if not gw:
            return False, "Couldn't identify the router on this wired network."
        out[name] = {"kind": "wired", "gw_macs": _merge(old.get("gw_macs"), gw, MAX_GW)}
    return True, out
