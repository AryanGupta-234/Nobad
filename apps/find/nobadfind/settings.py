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
        except (TypeError, ValueError, OverflowError):     # OverflowError: int(float("inf"))
            return d
    if key == "workers":
        try:
            return max(0, min(64, int(value)))
        except (TypeError, ValueError, OverflowError):
            return d
    if key in ("hotkey", "bar_hotkey"):
        v = str(value).lower().replace(" ", "")
        return v if _HOTKEY.match(v) else d
    if key in ("text_model", "photo_model"):
        from . import models
        return value if isinstance(value, str) and value in models.ids(key[:-6]) else d
    if key == "language_focus":
        return value if value in ("", "english", "multilingual", "hindi") else d
    if key == "games_mode":
        return value if value in ("smart", "always", "off") else d
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
                if raw.get("pause_fullscreen") is False and "games_mode" not in raw:
                    self.data["games_mode"] = "off"
        except (OSError, ValueError):
            pass

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def all(self):
        return dict(self.data)

    def update(self, changes):
        """Apply known keys only; returns the keys that changed. All or nothing: every value is checked first,
        then they are applied and saved together."""
        new = {k: coerce(k, v) for k, v in (changes or {}).items() if k in DEFAULTS}
        with self._lock:
            changed = [k for k, v in new.items() if v != self.data.get(k)]
            if changed:
                old = dict(self.data)
                self.data.update({k: new[k] for k in changed})
                try:
                    self._save()
                except Exception:
                    self.data = old                      # not saved: not changed
                    raise
        return changed

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)
