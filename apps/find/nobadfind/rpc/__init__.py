"""The engine's only door to the UI: JSON-RPC 2.0 over a private named pipe (see docs/STRUCTURE.md, ROADMAP §6).

The whole 0.7.0 API surface plus the engine's events; the contract is apps/find/contract (schemas, transcripts,
README), checked by tests/test_rpc_contract.py.
"""
from . import handlers
from .events import TICK, Events


class Rpc:
    """The pipe server, the handlers and the events, wired together for one Api."""

    def __init__(self, api, name=None, status_every=None, activity=None):
        from .server import Server                  # Windows only
        self.api = api
        self.server = Server(name=name)
        kw = {"every": status_every, "tick": min(TICK, status_every)} if status_every else {}
        self.events = Events(self.server.clients, self.server.drop, api, **kw)
        self.server.methods = handlers.methods(api, self.events)
        self.server.on_drop = self._dropped
        self.server.slow = set(handlers.SLOW)
        self.events.on_show = self.server.allow_foreground
        if activity is not None:
            activity.listen(self.events.activity)

    def start(self):
        if not self.server.start():
            return False
        self.events.start()
        return True

    def stop(self):
        self.events.stop()
        self.server.stop()

    def _dropped(self, conn):
        """Pipe liveness: a UI that ends (or crashes) without saying ui_hidden counts as its window closing. When
        it was the last UI, the engine hears it too (Wiring._all_closed: quit unless "stay_running" is on)."""
        self.events.gone(conn, self.api.hide)
        hook = getattr(self.api, "_on_all_closed", None)
        if hook is not None:
            hook()

    def show(self, what, text=None):
        """A hotkey asked for a window ("main" or "bar"): tell the UIs, and let them take the front."""
        return self.events.show(what, text)

    def ui_pids(self):
        return {c.pid for c in self.server.clients() if c.pid}
