"""What closing the window does.

- "hide": "Keep indexing in the background after closing" is on: the window hides, indexing goes on.
- "hide_idle": the setting is off (the default): indexing stops, every worker process ends, the models leave
  memory and the window hides. Only the main process stays, idle, so the hotkey still opens NOBAD Find;
  indexing resumes when the window opens again.
- "quit": "Quit NOBAD Find" was chosen, or the hotkey isn't working (a hidden Find could never be opened again).
"""
import threading


def on_close(settings, hotkey_ok, quitting):
    if quitting or not hotkey_ok:
        return "quit"
    return "hide" if settings.get("keep_background") else "hide_idle"


def after_hide(window, settings, hotkey_ok, quitting):
    """The window was hidden without closing it (Esc, "Hide after opening"): the same as closing it, so with
    background indexing off everything but the idle main process stops. Returns the settling thread, or None
    when indexing goes on (background indexing on) or there is no hotkey (just hidden, nothing stops)."""
    if on_close(settings, hotkey_ok, quitting) == "hide_idle":
        return window.wanted(True)
    return None


class Window:
    """Keeps the indexer matching the window: stopped (idle) while it's closed, running while it's open.
    wanted(idle) records the latest wish and settles it on a thread; settling re-reads the wish each round,
    so the latest wish wins, and a show that arrives while the old indexer thread is still ending keeps
    retrying until it can start. Once NOBAD Find is quitting (quitting() true) it settles nothing: quit's
    stop must be the last word, never followed by a start."""

    def __init__(self, indexer, idle, log=lambda *a: None, join_timeout=10, quitting=lambda: False):
        self.indexer, self.log, self.join_timeout = indexer, log, join_timeout
        self.quitting = quitting
        self.want_idle = idle
        self.stopping = False       # stop() was asked and the indexer may not have ended yet
        self.idle = idle            # the indexer has ended and its models are released
        self._lock = threading.Lock()

    def wanted(self, idle):
        self.want_idle = idle
        t = threading.Thread(target=self.settle, daemon=True, name="lifecycle")
        t.start()
        return t

    def settle(self):
        with self._lock:
            while True:
                if self.quitting():
                    return
                if self.want_idle and not self.idle:
                    if not self.stopping:
                        self.indexer.stop(keep_watching=True)   # the watcher keeps noting changes: no worker
                        self.stopping = True
                    if self.indexer.join(self.join_timeout):
                        self.indexer.release_models()
                        self.idle = True
                        self.log("window closed: indexing stopped, models released")
                    else:
                        self.log("indexing took long to stop", "warn")
                elif not self.want_idle and (self.idle or self.stopping):
                    if self.indexer.start():
                        self.idle = self.stopping = False
                        self.log("window opened: indexing resumes")
                    else:
                        self.indexer.join(self.join_timeout)    # the old thread is still ending: try again
                else:
                    return
