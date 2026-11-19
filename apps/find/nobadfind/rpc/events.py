"""Engine -> UI events, so the UI never polls (contract/events.schema.json, contract/README.md).

- `status` (the short status) and `status_full` (the Indexing page's full status) every STATUS_EVERY seconds, each
  only while some client subscribed to it: nobody listening means no work.
- `level` when the work level, its reason or the pause changes; `download` when a model download moves on.
  Both are noticed by a cheap look every TICK seconds at values the engine already holds.
- `activity` as each entry is added (Activity.listen), `show` / `here` / `notice` / `quitting` when they happen.
- A `notice` nobody hears waits (the last MAX_NOTICES) and goes to the first client that subscribes to notices.
"""
import threading
import time
from collections import deque

from ..api import DownloadRate
from ..log import log

EVENTS = {"status", "status_full", "level", "activity", "download", "notice", "show", "here", "quitting"}
STATUS_EVERY = 2.0                 # seconds between status events
TICK = 0.5                         # seconds between looks for level and download changes
MAX_NOTICES = 5


class Events:
    """Who wants what, and the ticker. `clients` returns the live connections; each has `.events` and `.shown`
    (sets) and `.send(obj) -> bool`; `drop(conn)` is called for one that can't take a message. `api` gives
    status_brief(), status() and downloads()."""

    def __init__(self, clients, drop, api, every=STATUS_EVERY, tick=TICK, clock=time.monotonic):
        self._clients, self._drop, self._api = clients, drop, api
        self._every, self._tick, self._clock = every, tick, clock
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()              # step() runs on the ticker; tests call it directly
        self._last_status = None
        self._level = None
        self._downloads = {}                       # model id -> (state, got, size, error) last seen
        self._rate = DownloadRate()
        self._notices = deque(maxlen=MAX_NOTICES)
        self.on_show = None                        # called before each show event (Server.allow_foreground)

    # ----- subscriptions -----
    def subscribe(self, conn, names):
        new = {n for n in names if n in EVENTS} - conn.events
        conn.events.update(new)
        if "notice" in new:
            while self._notices:
                text = self._notices.popleft()
                if not conn.send(_msg("notice", {"text": text})):
                    self._drop(conn)
                    break
        return sorted(conn.events)

    def unsubscribe(self, conn, names):
        conn.events.difference_update(names)
        return sorted(conn.events)

    def _wanted(self):
        out = set()
        for c in self._clients():
            out |= c.events
        return out

    def push(self, event, params):
        msg = _msg(event, params)
        sent = 0
        for c in self._clients():
            if event in c.events:
                if c.send(msg):
                    sent += 1
                else:
                    self._drop(c)
        return sent

    # ----- events that happen -----
    def activity(self, item):
        self.push("activity", {"t": float(item["t"]), "kind": str(item["kind"]), "text": str(item["text"])})

    def show(self, what, text=None):
        if self.on_show is not None:
            self._safe("foreground", self.on_show)       # the UIs may take the front (the pipe server's job)
        return self.push("show", {"what": what, "text": text})

    def here(self, path):
        return self.push("here", {"path": path or ""})

    def notice(self, text):
        if not self.push("notice", {"text": text}):
            self._notices.append(text)

    def quitting(self):
        return self.push("quitting", {})

    # ----- the main window, as the UIs report it -----
    def showing(self, window, but=None):
        return any(window in c.shown for c in self._clients() if c is not but)

    def ui_gone(self, conn):
        """conn's pipe closed: True if it showed the main window and no other client does."""
        return "main" in conn.shown and not self.showing("main", but=conn)

    # ----- the ticker -----
    def step(self, now):
        with self._lock:
            wanted = self._wanted()
            if "level" in wanted or "status" in wanted:
                self._safe("level", self._step_level, wanted)
            if "download" in wanted:
                self._safe("download", self._step_downloads, now)
            if self._last_status is None or now - self._last_status >= self._every - 1e-6:
                self._last_status = now
                if "status" in wanted:
                    self._safe("status", lambda: self.push("status", self._api.status_brief()))
                if "status_full" in wanted:
                    self._safe("status_full", lambda: self.push("status_full", self._api.status()))

    def _step_level(self, wanted):
        b = self._api.status_brief()
        level = {"level": b["level"], "reason": b["reason"], "paused": b["paused"]}
        prev, self._level = self._level, level
        if prev is not None and level != prev and "level" in wanted:
            self.push("level", level)

    def _step_downloads(self, now):
        for mid, m in self._api.downloads().items():
            key = (m["state"], m["got"], m["size"], m["error"])
            prev, self._downloads[mid] = self._downloads.get(mid), key
            rate = self._rate.sample(mid, m, now)
            if key == prev or (prev is None and m["state"] != "downloading"):
                continue
            self.push("download", {"id": mid, "state": m["state"], "got_mb": round(m["got"] / 1048576, 1),
                                   "size_mb": round(m["size"] / 1048576, 1),
                                   "mb_s": rate["mb_s"] if rate else 0.0, "error": str(m["error"] or "")})

    @staticmethod
    def _safe(what, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            log(f"rpc {what} event failed: {type(e).__name__}", "warn")

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="rpc-events")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self._tick):
            self.step(self._clock())


def _msg(event, params):
    return {"jsonrpc": "2.0", "method": event, "params": params}
