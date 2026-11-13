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


def coerce(key, value):
    """Validate a value coming from the UI. Returns (ok, value_or_error)."""
    if key not in DEFAULTS or key in ("settings_version", "dpapi_runtime_ok"):
        return False, "unknown setting"
    default = DEFAULTS[key]
    if key == "theme":
        return (value in ("dark", "light")), (value if value in ("dark", "light") else "theme must be dark or light")
    if key == "guard_service":
        return (value in SERVICES_IDS), (value if value in SERVICES_IDS else "unknown service")
    if key == "last_tab":
        return (isinstance(value, str) and re.fullmatch(r"t[1-9]", value) is not None), value
    if key == "fallback_dns":
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        import ipaddress
        try:
            for p in parts:
                ipaddress.ip_address(p)
        except ValueError:
            return False, "fallback DNS must be a comma-separated list of IP addresses"
        if not parts:
            return False, "enter at least one DNS server"
        return True, ", ".join(parts)
    if key == "ni_reference_dns":
        import ipaddress
        parts = [p.strip() for p in str(value).replace(";", ",").split(",") if p.strip()]
        try:
            for p in parts:
                ipaddress.ip_address(p)
        except ValueError:
            return False, "reference resolvers must be a comma-separated list of IP addresses"
        if len(parts) < 2:
            return False, "enter at least two independent resolvers so answers can be cross-checked"
        return True, ", ".join(parts[:8])
    if key in ("update_url", "crash_report_url"):
        v = str(value or "").strip()
        if v and not v.lower().startswith("https://"):
            return False, "must be an https:// URL"
        return True, v
    if key == "trusted_networks":
        if not isinstance(value, list):
            return False, "expected a list"
        out = []
        for x in value:
            x = str(x).strip()
            if x and len(x) <= 64 and x not in out:
                out.append(x)
        return True, out[:100]
    if key == "favorites":
        return (isinstance(value, list)), [str(x) for x in value][:200]
    if key in ("window", "last_region"):
        return True, value
    if isinstance(default, bool):
        return True, bool(value)
    return False, "unsupported"


def _sanitize(key, value):
    """A value read from disk gets the same validation as one from the UI (the file may be hand-edited or
    corrupted). Anything invalid falls back to the default instead of reaching e.g. a runtime config."""
    default = DEFAULTS[key]
    ok, v = coerce(key, value)
    if ok:
        return v
    if v in ("unknown setting", "unsupported"):  # not UI-settable: only check the type
        if default is None or value is None or type(value) is type(default) or (
                isinstance(default, (int, float)) and not isinstance(default, bool)
                and isinstance(value, (int, float)) and not isinstance(value, bool)):
            return value
    return default


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
