"""The engine's only door to the UI: JSON-RPC 2.0 over a private named pipe (see docs/STRUCTURE.md, ROADMAP §6).

Prototype scope (ROADMAP Phase 3 step 1): hello, subscribe, search, open, reveal, thumbnail, status, and the
`status` / `show` events. Phase 2 grows it to the whole 0.7.0 API surface.
"""
from . import handlers
from .events import Events


class Rpc:
    """The pipe server, the handlers and the events, wired together for one Api."""

    def __init__(self, api, name=None, status_every=None):
        from .server import Server                  # Windows only
        self.server = Server(name=name)
        kw = {"every": status_every} if status_every else {}
        self.events = Events(self.server.clients, self.server.drop, api.status_brief, **kw)
        self.server.methods = handlers.methods(api, self.events)

    def start(self):
        if not self.server.start():
            return False
        self.events.start()
        return True

    def stop(self):
        self.events.stop()
        self.server.stop()

    def show(self, what):
        """A hotkey asked for a window ("main" or "bar"): tell the UIs, and let them take the front."""
        self.server.allow_foreground()
        return self.events.push("show", {"what": what})
