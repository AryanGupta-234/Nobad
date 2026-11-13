"""Long-term usage history: daily totals, per-server totals, session log and speed-test history."""
import datetime
import json
import os
import threading
import time

KEEP_DAYS = 400
KEEP_SESSIONS = 500
KEEP_SPEED = 200


def _day(ts):
    return datetime.date.fromtimestamp(ts).isoformat()


class Usage:
    def __init__(self, path, legacy_sessions=None):
        self.path = path
        self.lock = threading.Lock()
        self.d = {"v": 1, "daily": {}, "sessions": [], "speed": [], "servers": {}}
        self._last_save = 0.0
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for k in self.d:
                    if k in loaded:
                        self.d[k] = loaded[k]
        except Exception:
            if legacy_sessions:
                self._import_legacy(legacy_sessions)

    def _import_legacy(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old = [x for x in json.load(f) if isinstance(x, dict)]
        except Exception:
            return
        for s in old:
            try:
                rec = {"name": str(s["name"]), "start": int(s["start"]), "secs": int(s["secs"]),
                       "rx": int(s.get("rx", 0)), "tx": int(s.get("tx", 0)), "avg_bps": 0, "peak_bps": 0}
            except (KeyError, TypeError, ValueError):
                continue
            self.d["sessions"].append(rec)
            self._bucket(rec["start"], rec["name"], rec["rx"], rec["tx"], rec["secs"], count=1)
        self.save(force=True)

    def _bucket(self, ts, name, rx, tx, secs, count=0):
        day = self.d["daily"].setdefault(_day(ts), {"rx": 0, "tx": 0, "secs": 0, "sessions": 0})
        day["rx"] += rx
        day["tx"] += tx
        day["secs"] += secs
        day["sessions"] += count
        sv = self.d["servers"].setdefault(name, {"rx": 0, "tx": 0, "secs": 0, "sessions": 0})
        sv["rx"] += rx
        sv["tx"] += tx
        sv["secs"] += secs
        sv["sessions"] += count

    def add_delta(self, name, rx, tx, secs, ts=None):
        """Called from the traffic loop; keeps totals correct even if the app crashes mid-session."""
        if rx <= 0 and tx <= 0 and secs <= 0:
            return
        with self.lock:
            self._bucket(ts or time.time(), name, max(0, int(rx)), max(0, int(tx)), max(0, int(secs)))
            self._trim()
        self.save()

    def log_session(self, rec):
        with self.lock:
            self.d["sessions"] = (self.d["sessions"] + [rec])[-KEEP_SESSIONS:]
            day = self.d["daily"].setdefault(_day(rec["start"]), {"rx": 0, "tx": 0, "secs": 0, "sessions": 0})
            day["sessions"] += 1
            sv = self.d["servers"].setdefault(rec["name"], {"rx": 0, "tx": 0, "secs": 0, "sessions": 0})
            sv["sessions"] += 1
        self.save(force=True)

    def add_speed(self, mbps, server=None, ts=None):
        with self.lock:
            self.d["speed"] = (self.d["speed"] + [{"ts": int(ts or time.time()), "mbps": float(mbps),
                                                   "server": server}])[-KEEP_SPEED:]
        self.save(force=True)

    def _trim(self):
        daily = self.d["daily"]
        if len(daily) > KEEP_DAYS:
            for k in sorted(daily)[: len(daily) - KEEP_DAYS]:
                del daily[k]

    def recent(self, n=8):
        """Last n sessions, oldest first (the UI reverses them)."""
        with self.lock:
            return list(self.d["sessions"][-n:])

    def summary(self, days=30, now=None):
        """days=0 means all time."""
        now = now or time.time()
        with self.lock:
            daily = dict(self.d["daily"])
            sessions = list(self.d["sessions"])
            speed = list(self.d["speed"])
            servers = {k: dict(v) for k, v in self.d["servers"].items()}
        if days:
            cutoff = _day(now - (days - 1) * 86400)
            daily = {k: v for k, v in daily.items() if k >= cutoff}
            sessions = [s for s in sessions if _day(s["start"]) >= cutoff]
            speed = [s for s in speed if _day(s["ts"]) >= cutoff]
        tot = {"rx": 0, "tx": 0, "secs": 0, "sessions": 0}
        for v in daily.values():
            for k in tot:
                tot[k] += v.get(k, 0)
        series = [{"day": k, **v} for k, v in sorted(daily.items())]
        return {"days": days, "totals": tot, "daily": series, "sessions": sessions[-100:][::-1], "speed": speed,
                "servers": sorted(({"name": k, **v} for k, v in servers.items()),
                                  key=lambda x: x["rx"] + x["tx"], reverse=True)}

    def save(self, force=False):
        now = time.time()
        if not force and now - self._last_save < 20:
            return
        self._last_save = now
        with self.lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.d, f)
                os.replace(tmp, self.path)
            except OSError:
                pass
