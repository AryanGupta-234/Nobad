"""Engine -> UI events: `status` every 2 s and `show` when a hotkey is pressed, to clients that subscribed."""
import threading

from ..log import log

EVENTS = {"status", "show"}
STATUS_EVERY = 2.0                 # seconds between status events


class Events:
    """Who wants what, and the status ticker. `clients` returns the live connections; each has `.events` (a set)
    and `.send(obj) -> bool`; `drop(conn)` is called for one that can't take a message."""

    def __init__(self, clients, drop, status, every=STATUS_EVERY):
        self._clients, self._drop, self._status = clients, drop, status
        self._every = every
        self._stop = threading.Event()
        self._thread = None

    def subscribe(self, conn, names):
        conn.events.update(n for n in names if n in EVENTS)
        return sorted(conn.events)

    def push(self, event, params):
        msg = {"jsonrpc": "2.0", "method": event, "params": params}
        sent = 0
        for c in self._clients():
            if event in c.events:
                if c.send(msg):
                    sent += 1
                else:
                    self._drop(c)
        return sent

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="rpc-status")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self._every):
            if not any("status" in c.events for c in self._clients()):
                continue                                   # nobody listening: don't even ask
            try:
                st = self._status()
            except Exception as e:
                log(f"rpc status event failed: {type(e).__name__}", "warn")
                continue
            self.push("status", st)
