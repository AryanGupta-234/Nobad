"""The engine's pipe for NOBAD's Flutter window: JSON-RPC 2.0 over a private named pipe (docs/UI-PIPE.md).

It sits next to the loopback HTTP server (which the WebView UI and the single-instance hand-off still use) until
the Flutter UI has replaced the WebView everywhere. The contract is apps/vpn/contract (schemas, transcripts,
README), checked by tests/test_rpc_contract.py.
"""
import os
import threading

from ..const import APP_VER
from ..ctx import ctx
from ..logbus import log, set_ui_visible
from . import launch, methods
from .events import Events


def about():
    return {"app": "NOBAD VPN", "version": APP_VER, "pid": os.getpid()}


class Rpc:
    """The pipe server, the methods and the events, wired together. `owns_windows`: the Flutter UI is NOBAD's
    window (it reports what is on screen, so it decides the engine's pace); False when the WebView is too."""

    def __init__(self, handlers=None, state=None, name=None, user_sid=None, check=None, owns_windows=True,
                 launch_ui=None):
        from .server import Server                  # Windows only
        self.server = Server(name=name, user_sid=user_sid, check=check)
        self.events = Events(self.server.clients, self.server.drop)
        self.server.methods = methods.build(
            handlers if handlers is not None else methods.engine_handlers(),
            state or (lambda: ctx.tunnel.state()), self.events,
            on_visible=set_ui_visible if owns_windows else None,
            launch_ui=launch_ui if launch_ui is not None else launch.launch, about=about)
        self.server.on_connect = lambda conn: self.events.clients_changed()
        self.server.on_drop = self._dropped
        self._owns = owns_windows

    def start(self):
        return self.server.start()

    def stop(self):
        try:
            self.events.quitting()
        except Exception:
            pass
        self.events.stop()
        self.server.stop()

    def _dropped(self, conn):
        self.events.clients_changed()
        if self._owns:                               # a UI that ended without ui_hidden: its windows are gone
            set_ui_visible(any(c.shown for c in self.server.clients()))

    def show(self, window):
        """Show a window ("main" / "mini"): the UI that serves it brings it up; with no UI running, start one."""
        if any(window in c.serves for c in self.server.clients()):
            return self.events.show(window) > 0
        return launch.launch(window)


class FlutterWindows:
    """ctx.windows when the Flutter UI is NOBAD's window: the same calls the tray, the hand-off and request_quit
    make on window.WindowManager, answered through the pipe. The engine owns no window of its own."""

    main = True                                     # app._background_start: "there is a window" (no splash wait)

    def __init__(self, rpc):
        self.rpc = rpc
        self.revealed_event = threading.Event()
        self.revealed_event.set()

    def create(self, start_hidden=False, on_shown=None):
        if on_shown:
            on_shown()
        if not start_hidden:
            self.show_main()
        return True

    def run(self):
        ctx.quit_event.wait()

    def show_main(self):
        threading.Thread(target=self.rpc.show, args=("main",), daemon=True, name="ui-show").start()

    def toggle_mini(self):
        threading.Thread(target=self.rpc.show, args=("mini",), daemon=True, name="ui-show").start()

    def hide_mini(self):
        pass                                         # the pop-up hides itself (focus lost, Esc)

    def titlebar_action(self, act, edge=None):
        return {"maximized": False}

    HT = {}

    def save_state(self):
        pass

    def destroy_all(self):
        try:
            self.rpc.events.quitting()
        except Exception as e:
            log(f"engine pipe: quitting event failed: {type(e).__name__}", "warn")


def start(mode):
    """Start the pipe for `mode` ("flutter" or "both"). Returns the Rpc, or None if it couldn't start."""
    if os.name != "nt" or mode not in ("flutter", "both"):
        return None
    try:
        rpc = Rpc(owns_windows=(mode == "flutter"))
    except OSError as e:
        log(f"engine pipe not available: {e}", "warn")
        return None
    return rpc if rpc.start() else None
