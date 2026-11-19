"""Engine -> UI events over the pipe: every logbus.broadcast (the same events the WebView's /events stream gets),
as JSON-RPC notifications whose method is the event's type, sent only to clients that subscribed to that type.

The pump subscribes to logbus only while at least one checked client is connected: with no window, nothing is
queued, and logbus.has_subscribers() stays false, so the engine keeps its slow background pace (traffic every
30 s instead of 2 s). The engine's own `show` and `quitting` events come from here as well.
"""
import json
import queue
import threading

from .. import logbus
from ..logbus import log
from .protocol import encode, notification

# What a UI may subscribe to. The engine's broadcasts (ARCHITECTURE.md 7.3) plus the pipe's own show/quitting.
EVENTS = {"state", "log", "health", "traffic", "probe", "ipinfo", "speed", "speed_done", "stream_start", "stream",
          "stream_done", "network_diagnose", "valorant_start", "valorant_result", "valorant_done", "gaming_probe",
          "endpoint_report", "error_action", "notify", "fix_result", "update", "guard", "task_done",
          "net_repair_start", "net_repair_done", "reach_report", "et_report", "direct_health",
          "ni_overview", "ni_progress", "ni_investigation", "ni_lookup", "ni_vpn", "ni_fix", "ni_fix_start",
          "si_title", "si_restrictions", "si_verify",
          "show", "quitting"}


class Events:
    """`clients()` returns the live, checked connections (each has .events, .send(obj|bytes) -> bool);
    `drop(conn)` is called for one that can't take a message."""

    def __init__(self, clients, drop, bus=logbus):
        self._clients, self._drop, self._bus = clients, drop, bus
        self._lock = threading.Lock()
        self._q = None
        self._thread = None

    # ----- subscriptions -----
    def subscribe(self, conn, names):
        conn.events.update(n for n in names if n in EVENTS)
        return sorted(conn.events)

    def unsubscribe(self, conn, names):
        conn.events.difference_update(names)
        return sorted(conn.events)

    # ----- delivery -----
    def push(self, event, params):
        line = encode(notification(event, params))
        sent = 0
        for c in self._clients():
            if event in c.events:
                if c.send(line):
                    sent += 1
                else:
                    self._drop(c)
        return sent

    def show(self, window):
        return self.push("show", {"window": window})

    def quitting(self):
        return self.push("quitting", {})

    def deliver(self, raw):
        """One logbus message (a JSON string {"type", "payload"}) to the clients that want it."""
        try:
            m = json.loads(raw)
            kind, payload = m.get("type"), m.get("payload")
        except (ValueError, AttributeError):
            return 0
        if kind not in EVENTS:
            return 0
        return self.push(kind, payload)

    # ----- the pump: on while someone is connected -----
    def clients_changed(self):
        """Call after a client was admitted or dropped: starts or stops listening to logbus."""
        with self._lock:
            want = bool(self._clients())
            if want and self._q is None:
                self._q = self._bus.subscribe(maxsize=600)
                self._thread = threading.Thread(target=self._pump, args=(self._q,), daemon=True, name="rpc-events")
                self._thread.start()
            elif not want and self._q is not None:
                q, self._q = self._q, None
                self._bus.unsubscribe(q)
                try:
                    q.put_nowait(None)              # wake the pump so it ends
                except queue.Full:
                    pass

    def _pump(self, q):
        while True:
            raw = q.get()
            if raw is None or self._q is not q:
                return
            try:
                self.deliver(raw)
            except Exception as e:
                log(f"engine pipe event failed: {type(e).__name__}", "warn")

    def stop(self):
        with self._lock:
            q, self._q = self._q, None
        if q is not None:
            self._bus.unsubscribe(q)
            try:
                q.put_nowait(None)
            except queue.Full:
                pass
