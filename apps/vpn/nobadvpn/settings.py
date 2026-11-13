"""Versioned, validated settings stored in ProgramData."""
import json
import os
import re
import threading

from .const import DEFAULTS, SETTINGS_VERSION

SERVICES_IDS = ("", "netflix", "youtube", "disney", "prime", "spotify", "twitch")
_IP_OR_HOST = re.compile(r"^[A-Za-z0-9.:\-]+$")


def _migrate_1_to_2(d):
    # v1 (single-file era) had only a handful of keys; v2 adds many. Defaults fill the rest.
    d.setdefault("wizard_done", bool(d.get("last_region")))  # existing users skip the first-run wizard
    return d


MIGRATIONS = {1: _migrate_1_to_2}


def migrate(d):
    v = d.get("settings_version", 1)
    if not isinstance(v, int):
        v = 1
    while v < SETTINGS_VERSION:
        fn = MIGRATIONS.get(v)
        if fn:
            d = fn(d)
        v += 1
    d["settings_version"] = SETTINGS_VERSION
    return d


# Written by NOBAD itself or by a dedicated handler (favourites, streaming prefs, window, trust), never through the
# generic "settings" call. They are still checked when read from disk (see _CLEAN).
INTERNAL = ("settings_version", "dpapi_runtime_ok", "trusted_fingerprints", "window", "last_region", "favorites",
            "si_my_services", "si_language")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
MAX_TEXT = 300


def _ip_list(value, what, lo, hi):
    import ipaddress
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        return False, f"{what} must be a comma-separated list of IP addresses"
    parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    try:
        parts = [str(ipaddress.ip_address(p)) for p in parts]
    except ValueError:
        return False, f"{what} must be a comma-separated list of IP addresses"
    return (len(parts) >= lo), (", ".join(parts[:hi]) if len(parts) >= lo else None)


def _https_url(value):
    from urllib.parse import urlsplit
    if not isinstance(value, str):
        return False, "must be an https:// URL"
    v = value.strip()
    if not v:
        return True, ""
    if len(v) > MAX_TEXT or _CTRL.search(v) or " " in v:
        return False, "must be an https:// URL"
    try:
        u = urlsplit(v)
        host = u.hostname
    except ValueError:
        return False, "must be an https:// URL"
    if u.scheme.lower() != "https" or not host or u.username or u.password:
        return False, "must be an https:// URL with a host name (no user name or password)"
    return True, v


def _name_list(value, n, max_len=64):
    if not isinstance(value, list):
        return None
    out = []
    for x in value[:1000]:
        if not isinstance(x, str):
            continue
        x = x.strip()
        if x and len(x) <= max_len and not _CTRL.search(x) and x not in out:
            out.append(x)
    return out[:n]


def coerce(key, value):
    """Validate a value coming from the UI. Returns (ok, value_or_error)."""
    if key not in DEFAULTS or key in INTERNAL:
        return False, "unknown setting"
    default = DEFAULTS[key]
    if key == "theme":
        return (value in ("dark", "light")), (value if value in ("dark", "light") else "theme must be dark or light")
    if key == "guard_service":
        return (value in SERVICES_IDS), (value if value in SERVICES_IDS else "unknown service")
    if key == "last_tab":
        ok = isinstance(value, str) and re.fullmatch(r"t[1-9]", value) is not None
        return ok, (value if ok else "unknown tab")
    if key == "fallback_dns":
        ok, v = _ip_list(value, "fallback DNS", 1, 4)
        return (True, v) if ok else (False, v or "enter at least one DNS server")
    if key == "ni_reference_dns":
        ok, v = _ip_list(value, "reference resolvers", 2, 8)
        return (True, v) if ok else (False, v or "enter at least two independent resolvers so answers can be cross-checked")
    if key in ("update_url", "crash_report_url"):
        return _https_url(value)
    if key == "trusted_networks":
        out = _name_list(value, 100)
        return (False, "expected a list") if out is None else (True, out)
    if isinstance(default, bool):
        b = _as_bool(value)
        return (False, "expected true or false") if b is None else (True, b)
    return False, "unsupported"


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _clean_window(v):
    if not isinstance(v, dict):
        return None
    out = {}
    for k in ("x", "y", "w", "h"):
        if isinstance(v.get(k), int) and not isinstance(v.get(k), bool) and -100000 <= v[k] <= 100000:
            out[k] = v[k]
    out["maximized"] = v.get("maximized") is True
    return out


def _clean_region(v):
    return v if isinstance(v, str) and 0 < len(v) <= 64 and not _CTRL.search(v) else None


def _clean_services(v):
    if not isinstance(v, list):
        return []
    return sorted({x for x in v[:200] if isinstance(x, int) and not isinstance(x, bool) and 0 < x < 10**7})


def _clean_language(v):
    return v if isinstance(v, str) and re.fullmatch(r"[a-z]{2,3}(-[A-Z]{2})?", v) else DEFAULTS["si_language"]


_MAC_RE = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")


def clean_fingerprints(value):
    """trusted_fingerprints as read from disk: keep only well-formed entries (a hand-edited file can't widen trust)."""
    out = {}
    if not isinstance(value, dict):
        return out
    for name, fp in list(value.items())[:100]:
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or not isinstance(fp, dict):
            continue
        macs = lambda k, n: [m for m in (fp.get(k) or [])[:n] if isinstance(m, str) and _MAC_RE.fullmatch(m)]
        if fp.get("kind") == "wifi":
            e = {"kind": "wifi"}
            auth, b, g = fp.get("auth"), macs("bssids", 16), macs("gw_macs", 4)
            if isinstance(auth, str) and 0 < len(auth) <= 40 and auth.strip().lower() not in ("open", "none") and b:
                e.update(auth=auth, bssids=b)
            if g:
                e["gw_macs"] = g
            if len(e) > 1:
                out[name] = e
        elif fp.get("kind") == "wired":
            g = macs("gw_macs", 4)
            if g:
                out[name] = {"kind": "wired", "gw_macs": g}
    return out


def _sanitize(key, value):
    """A value read from disk gets the same validation as one from the UI (the file may be hand-edited or
    corrupted). Anything invalid falls back to the default instead of reaching e.g. a runtime config."""
    default = DEFAULTS[key]
    if key in _CLEAN:
        return _CLEAN[key](value)
    ok, v = coerce(key, value)
    if ok:
        return v
    if v in ("unknown setting", "unsupported"):  # not UI-settable: only check the type
        if default is None or value is None or type(value) is type(default) or (
                isinstance(default, (int, float)) and not isinstance(default, bool)
                and isinstance(value, (int, float)) and not isinstance(value, bool)):
            return value
    return default


_CLEAN = {"trusted_fingerprints": lambda v: clean_fingerprints(v), "window": _clean_window, "last_region": _clean_region,
          "favorites": lambda v: _name_list(v, 200) or [], "si_my_services": _clean_services,
          "si_language": _clean_language}


class Settings:
    def __init__(self, path, legacy_path=None):
        self.path = path
        self.lock = threading.Lock()
        self.d = dict(DEFAULTS)
        self.migrated_from = None
        saved = self._read(path)
        if saved is None and legacy_path:
            saved = self._read(legacy_path)
            if saved is not None:
                self.migrated_from = legacy_path
        dirty = False
        if saved is not None:
            old_ver = saved.get("settings_version", 1)
            saved = migrate(dict(saved))
            dirty = old_ver != saved["settings_version"]
            for k in DEFAULTS:
                if k in saved:
                    v = _sanitize(k, saved[k])
                    dirty = dirty or v != saved[k]
                    self.d[k] = v
        if self.migrated_from or dirty or (saved is not None and not os.path.exists(path)):
            self._write()

    @staticmethod
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    def _write(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def get(self, k):
        with self.lock:
            return self.d.get(k)

    def set(self, k, v):
        with self.lock:
            self.d[k] = v
            self._write()

    def update(self, **kw):
        with self.lock:
            self.d.update(kw)
            self._write()

    def snapshot(self):
        with self.lock:
            return dict(self.d)
