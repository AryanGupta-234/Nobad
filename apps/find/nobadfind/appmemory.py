"""Remembers which apps needed room, so NOBAD Find can start gentler next time.

Only the exe file name (lowercase) is kept, never a path or a window title.
Time comes only from ``Sample.t``; there is no hidden clock here.
"""
import json
import threading

from . import governor as g

WINDOW_DAYS = 30
QUIET_STEP = 3
MAX_NAME = 64
_UP = {g.PAUSED: g.LIGHT, g.LIGHT: None}


def _norm(exe):
    if not isinstance(exe, str):
        return None
    exe = exe.strip().lower()
    if not exe or len(exe) > MAX_NAME or "/" in exe or "\\" in exe:
        return None
    return exe


def _reason(level, lags):
    if level is None:
        return "No recent lag, so NOBAD Find works normally while it runs."
    if level == g.PAUSED:
        n = "twice" if lags == 2 else f"{lags} times"
        return f"Lagged {n} in the last {WINDOW_DAYS} days, so NOBAD Find pauses while it runs."
    if lags <= 1:
        return "Lagged once, so NOBAD Find works with 1 worker while it runs."
    return (f"Lagged {lags} times in the last {WINDOW_DAYS} days but has been quiet lately, "
            "so NOBAD Find works with 1 worker while it runs.")


class AppMemory:
    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()

    def _load(self, exe):
        for e, raw in self.store.app_rows():
            if e == exe:
                try:
                    return json.loads(raw)
                except ValueError:
                    break
        return None

    def _save(self, exe, d):
        self.store.set_app(exe, json.dumps(d))

    def record_lag(self, exe, s):
        exe = _norm(exe)
        if exe is None:
            return
        with self._lock:
            d = self._load(exe) or {"lags": [], "seen": 0, "worst_cpu": None, "worst_gpu": None,
                                    "quiet": 0, "level": None, "last_seen": None}
            newest = max([s.t] + d["lags"])
            d["lags"] = [t for t in d["lags"] + [s.t] if t >= newest - WINDOW_DAYS * 86400]
            for k, v in (("worst_cpu", s.cpu), ("worst_gpu", s.gpu)):
                if v is not None and (d[k] is None or v > d[k]):
                    d[k] = v
            d["last_seen"] = newest
            d["seen"] += 1
            d["quiet"] = 0
            want = g.PAUSED if len(d["lags"]) >= 2 else g.LIGHT
            d["level"] = want if g.ORDER.index(want) < g.ORDER.index(d["level"] or g.FULL) else d["level"]
            self._save(exe, d)

    def quiet_session(self, exe):
        exe = _norm(exe)
        if exe is None:
            return
        with self._lock:
            d = self._load(exe)
            if d is None or d["level"] is None:
                return
            d["seen"] += 1
            d["quiet"] += 1
            if d["quiet"] >= QUIET_STEP:
                d["level"] = _UP.get(d["level"])
                d["quiet"] = 0
            self._save(exe, d)

    def start_level(self, exe):
        exe = _norm(exe)
        if exe is None:
            return None
        with self._lock:
            d = self._load(exe)
        return d["level"] if d else None

    def list(self):
        with self._lock:
            rows = self.store.app_rows()
        out = []
        for exe, raw in rows:
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            out.append({"exe": exe, "seen": d["seen"], "lag_events": len(d["lags"]),
                        "worst_cpu": d["worst_cpu"], "worst_gpu": d["worst_gpu"], "start_level": d["level"],
                        "last_seen": d["last_seen"], "reason": _reason(d["level"], len(d["lags"]))})
        return sorted(out, key=lambda r: r["exe"])

    def reset(self, exe=None):
        with self._lock:
            if exe is None:
                self.store.drop_app(None)
            else:
                name = _norm(exe)
                if name is not None:
                    self.store.drop_app(name)
