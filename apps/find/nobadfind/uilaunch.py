"""Start the Flutter UI when a window is asked for (a hotkey, the tray) and no UI is connected to the pipe.

The UI is started outside Find's job (winapi.start_outside_job: a normal breakaway, an argument list, as the same
normal user; the engine never runs elevated), so closing the UI and quitting the engine stay independent. It gets the
page to open: --page search|settings|index, or --bar for the quick find bar.

Where the UI is: next to the engine exe in the installed app (nobad_find.exe); from source, NOBAD_FIND_UI_EXE or the
Flutter release build in apps/find/ui_flutter.
"""
import os
import sys
import time

from .log import log

UI_NAME = "nobad_find.exe"
DEV_BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui_flutter", "build",
                         "windows", "x64", "runner", "Release", UI_NAME)
PAGES = {"main": "search", "search": "search", "settings": "settings", "index": "index"}
STARTING = 15.0                 # seconds a UI being started has to connect before another start is tried
NO_UI = "NOBAD Find's window isn't installed. Reinstall NOBAD Find to get it back."


def ui_exe():
    """The UI's exe, or None when there is none."""
    if getattr(sys, "frozen", False):
        p = os.path.join(os.path.dirname(sys.executable), UI_NAME)
        return p if os.path.isfile(p) else None
    env = os.environ.get("NOBAD_FIND_UI_EXE", "")
    if env and os.path.isfile(env):
        return env
    return DEV_BUILD if os.path.isfile(DEV_BUILD) else None


def argv_for(exe, what):
    return [exe, "--bar"] if what == "bar" else [exe, "--page", PAGES.get(what, "search")]


def start_now(what, exe=ui_exe, start=None, clock=time.monotonic):
    """Start the UI on that page without waiting for the engine (NobadFind.exe's first start: the window comes up
    while the engine loads, and connects when the pipe is ready). The start time, or None if it didn't start."""
    from . import winapi
    path = exe()
    if not path:
        log("no UI to start (nobad_find.exe not found)", "warn")
        return None
    try:
        (start or winapi.start_outside_job)(argv_for(path, what))
    except OSError as e:
        log(f"could not start the UI (error {e.winerror or e.errno})", "warn")
        return None
    log(f"started the UI ({PAGES.get(what, what)})")
    return clock()


class Launcher:
    """show(what): the `show` event when a UI is connected, else start one on that page (once per STARTING)."""

    def __init__(self, events, connected, exe=ui_exe, start=None, clock=time.monotonic, note=None):
        from . import winapi
        self.events, self.connected, self.exe, self.clock = events, connected, exe, clock
        self.start = start or winapi.start_outside_job
        self.note = note or (lambda text: None)
        self._started_at = None
        self._told = False

    def started(self, at):
        """A UI was started at `at` (start_now): within STARTING, show() waits for it instead of starting another."""
        self._started_at = at

    def here(self, path):
        return self.events.here(path)

    def show(self, what, text=None):
        if self.connected():
            self._started_at = None
            return self.events.show(what, text)
        now = self.clock()
        if self._started_at is not None and now - self._started_at < STARTING:
            return None                         # one is starting already; it opens on the page it was given
        exe = self.exe()
        if not exe:
            if not self._told:
                self._told = True
                log("no UI to start (nobad_find.exe not found)", "warn")
                self.note(NO_UI)
            return None
        try:
            self.start(argv_for(exe, what))
            self._started_at = now
            log(f"started the UI ({PAGES.get(what, what)})")
        except OSError as e:
            log(f"could not start the UI (error {e.winerror or e.errno})", "warn")
        return None
