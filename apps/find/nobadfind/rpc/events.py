"""Engine -> UI events, so the UI never polls (contract/events.schema.json, contract/README.md).

- `status` (the short status) and `status_full` (the Indexing page's full status) every STATUS_EVERY seconds, each
  only while some client subscribed to it: nobody listening means no work.
- `level` when the work level, its reason or the pause changes; `download` when a model download moves on.
  Both are noticed by a cheap look every TICK seconds at values the engine already holds.
- `activity` for each entry added (Activity.listen), sent by the ticker: the governor thread that adds an entry
  never waits for a slow client. `show` / `here` / `notice` / `quitting` go out when they happen.
- A `notice` nobody hears waits (the last MAX_NOTICES) and goes to the first client that subscribes to notices.
"""
import threading
import time
from collections import deque

from ..api import DownloadRate
from ..log import log

EVENTS = {"status", "status_full", "level", "activity", "download", "notice", "show", "here", "quitting", "models"}
MODELS_EVERY = 1.0                 # seconds between looks for a changed models answer (it reads the model folders)
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
        self._lock = threading.Lock()              # step()'s own state; never held while sending
        self._windows = threading.Lock()           # ui_shown / ui_hidden / a client gone, one at a time
        self._last_status = None
        self._level = None
        self._downloads = {}                       # model id -> (state, got, size, error) last seen
        self._rate = DownloadRate()
        self._notices = deque(maxlen=MAX_NOTICES)
        self._activity = deque(maxlen=50)          # entries added since the last tick
        self.on_show = None                        # called before each show event (Server.allow_foreground)

    # ----- subscriptions -----
    def subscribe(self, conn, names):
        new = {n for n in names if n in EVENTS} - conn.events
        conn.events.update(new)
        if "notice" in new:
            while self._notices:
                text = self._notices.popleft()
                if not conn.send(_msg("notice", {"text": text})):
                    self._notices.appendleft(text)     # not heard after all: it waits for the next listener
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
        """Activity.listen: called on the thread that added the entry; the next tick sends it."""
        self._activity.append({"t": float(item["t"]), "kind": str(item["kind"]), "text": str(item["text"])})

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
    # A connection's requests can still be running after its pipe closed (the reader saw the end first). These
    # three take turns, and a dropped connection (alive False) can't show a window any more, so a late ui_shown
    # can never resume indexing for a UI that is gone.
    def showing(self, window, but=None):
        return any(window in c.shown for c in self._clients() if c is not but)

    def ui_gone(self, conn):
        """conn's pipe closed: True if it showed the main window and no other client does."""
        return "main" in conn.shown and not self.showing("main", but=conn)

    def shown(self, conn, window, on_main):
        """ui_shown: mark it and, for the main window, call on_main(). Nothing for a dropped connection."""
        with self._windows:
            if conn is not None:
                if not getattr(conn, "alive", True):
                    return False
                conn.shown.add(window)
            if window == "main":
                on_main()
            return True

    def hidden(self, conn, window, on_main):
        """ui_hidden: on_main() when the main window is now shown by no client."""
        with self._windows:
            if conn is not None:
                conn.shown.discard(window)
            if window == "main" and not self.showing("main"):
                on_main()

    def gone(self, conn, on_main):
        """conn's pipe closed (pipe liveness): counts as ui_hidden for every window it showed."""
        with self._windows:
            last = self.ui_gone(conn)
            conn.shown.clear()
            if last:
                on_main()

    # ----- the ticker -----
    def step(self, now):
        """One look: work out what to send while holding the ticker's lock, then send without it."""
        out = []
        with self._lock:
            wanted = self._wanted()
            while self._activity:
                item = self._activity.popleft()
                if "activity" in wanted:
                    out.append(("activity", item))
            if "level" in wanted or "status" in wanted:
                self._safe("level", self._step_level, wanted, out)
            if "download" in wanted:
                self._safe("download", self._step_downloads, now, out)
            if "models" in wanted and now - self._models_at >= MODELS_EVERY - 1e-6:
                self._models_at = now
                self._safe("models", self._step_models, out)
            if self._last_status is None or now - self._last_status >= self._every - 1e-6:
                self._last_status = now
                if "status" in wanted:
                    self._safe("status", lambda: out.append(("status", self._api.status_brief())))
                if "status_full" in wanted:
                    self._safe("status_full", lambda: out.append(("status_full", self._api.status())))
        for event, params in out:
            self._safe(event, self.push, event, params)

    def _step_level(self, wanted, out):
        b = self._api.status_brief()
        level = {"level": b["level"], "reason": b["reason"], "paused": b["paused"]}
        prev, self._level = self._level, level
        if prev is not None and level != prev and "level" in wanted:
            out.append(("level", level))

    _models_at = -1e9
    _models_last = None

    def _step_models(self, out):
        m = self._api.models()
        if m != self._models_last:
            if self._models_last is not None:
                out.append(("models", m))
            self._models_last = m

    def _step_downloads(self, now, out):
        for mid, m in self._api.downloads().items():
            key = (m["state"], m["got"], m["size"], m["error"])
            prev = self._downloads.get(mid)
            if key == prev:
                continue                    # nothing new: the speed keeps counting from the last change
            self._downloads[mid] = key
            rate = self._rate.sample(mid, m, now)
            if prev is None and m["state"] != "downloading":
                continue
            out.append(("download", {"id": mid, "state": m["state"], "got_mb": round(m["got"] / 1048576, 1),
                                     "size_mb": round(m["size"] / 1048576, 1),
                                     "mb_s": rate["mb_s"] if rate else 0.0, "error": str(m["error"] or "")}))

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
