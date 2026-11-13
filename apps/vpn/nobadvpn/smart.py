"""Learns which server works best, by time of day and per streaming service.

Latency: an exponential moving average per (server, 4-hour block of the day).
Services: when a check for a service fails on a server, that server is marked blocked for that service for 24 h.
"""
import json
import os
import threading
import time

BLOCK_HOURS = 4
EMA_ALPHA = 0.3
BLOCK_SECS = 24 * 3600
FAIL_PENALTY_MS = 60
FAIL_DECAY_SECS = 24 * 3600


def block_of(ts):
    return time.localtime(ts).tm_hour // BLOCK_HOURS


class Smart:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.d = {"v": 1, "lat": {}, "svc": {}, "fail": {}, "wins": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for k in self.d:
                    if isinstance(loaded.get(k), dict):
                        self.d[k] = loaded[k]
        except Exception:
            pass

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def record_latency(self, server, rtt, now=None):
        if rtt is None:
            return
        now = now or time.time()
        b = str(block_of(now))
        with self.lock:
            cell = self.d["lat"].setdefault(server, {}).get(b)
            if cell:
                cell["ema"] = round(cell["ema"] * (1 - EMA_ALPHA) + rtt * EMA_ALPHA, 2)
                cell["n"] += 1
            else:
                self.d["lat"][server][b] = {"ema": float(rtt), "n": 1}
            self._save()

    def record_service(self, server, service, ok, now=None):
        now = now or time.time()
        with self.lock:
            rec = self.d["svc"].setdefault(server, {}).setdefault(service, {"ok": 0, "bad": 0, "blocked_until": 0})
            if ok:
                rec["ok"] += 1
                rec["blocked_until"] = 0
            else:
                rec["bad"] += 1
                rec["blocked_until"] = now + BLOCK_SECS
            rec["last"] = now
            self._save()

    def record_result(self, server, success, now=None):
        now = now or time.time()
        with self.lock:
            if success:
                self.d["fail"].pop(server, None)
                self.d["wins"][server] = self.d["wins"].get(server, 0) + 1
            else:
                f = self.d["fail"].setdefault(server, {"n": 0, "last": now})
                f["n"] += 1
                f["last"] = now
            self._save()

    def is_blocked(self, server, service, now=None):
        if not service:
            return False
        now = now or time.time()
        with self.lock:
            rec = self.d["svc"].get(server, {}).get(service)
            return bool(rec and rec.get("blocked_until", 0) > now)

    def _expected_latency(self, server, now):
        cells = self.d["lat"].get(server, {})
        cell = cells.get(str(block_of(now)))
        if cell:
            return cell["ema"]
        if cells:
            return sum(c["ema"] for c in cells.values()) / len(cells)
        return None

    def score(self, server, now=None, service=None, live_rtt=None):
        """Lower is better; None means 'unusable for this request'."""
        now = now or time.time()
        if self.is_blocked(server, service, now):
            return None
        with self.lock:
            exp = self._expected_latency(server, now)
            f = self.d["fail"].get(server)
            pen = 0.0
            if f:
                age = max(0.0, now - f.get("last", now))
                pen = FAIL_PENALTY_MS * f.get("n", 0) * max(0.0, 1 - age / FAIL_DECAY_SECS)
        if live_rtt is not None and exp is not None:
            base = 0.6 * live_rtt + 0.4 * exp
        elif live_rtt is not None:
            base = float(live_rtt)
        elif exp is not None:
            base = exp
        else:
            base = 500.0  # never measured: try it after everything we know works
        return base + pen

    def rank(self, servers, now=None, service=None, live=None):
        live = live or {}
        out = []
        for s in servers:
            sc = self.score(s, now, service, live.get(s))
            if sc is not None:
                out.append((s, sc))
        return sorted(out, key=lambda x: x[1])

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.d))
