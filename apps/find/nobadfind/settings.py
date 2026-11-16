"""Settings: a small JSON file, every value checked against DEFAULTS before it is used or saved."""
import json
import os
import re
import threading

from .const import DEFAULTS

_HOTKEY = re.compile(r"^(?:(?:ctrl|alt|shift|win)\+){1,3}(?:[a-z0-9]|space|f(?:[1-9]|1[0-2]))$")
WSEARCH_STARTS = ("", "auto", "delayed-auto", "demand", "disabled")


def _paths(v):
    if not isinstance(v, list):
        return []
    out = []
    for p in v[:200]:
        if isinstance(p, str) and 2 < len(p) < 1024 and os.path.isabs(p) and "\x00" not in p:
            out.append(os.path.normpath(p))
    return list(dict.fromkeys(out))


def coerce(key, value):
    """Return a safe value for key, or the default if value doesn't fit."""
    d = DEFAULTS[key]
    if key in ("roots", "exclude"):
        return _paths(value)
    if key == "content_max_mb":
        try:
            return max(1, min(500, int(value)))
        except (TypeError, ValueError):
            return d
    if key == "workers":
        try:
            return max(0, min(64, int(value)))
        except (TypeError, ValueError):
            return d
    if key == "hotkey":
        v = str(value).lower().replace(" ", "")
        return v if _HOTKEY.match(v) else d
    if key == "wsearch_prev":
        return value if value in WSEARCH_STARTS else d
    if key == "theme":
        return value if value in ("dark", "light") else d
    if isinstance(d, bool):
        return value if isinstance(value, bool) else d
    return d


class Settings:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k in DEFAULTS:
                    if k in raw:
                        self.data[k] = coerce(k, raw[k])
        except (OSError, ValueError):
            pass

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def all(self):
        return dict(self.data)

    def update(self, changes):
        """Apply known keys only; returns the keys that changed."""
        changed = []
        with self._lock:
            for k, v in (changes or {}).items():
                if k in DEFAULTS:
                    nv = coerce(k, v)
                    if nv != self.data.get(k):
                        self.data[k] = nv
                        changed.append(k)
            if changed:
                self._save()
        return changed

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)
