"""A small in-memory log of recent governor decisions, for the UI. Never stored.

Listeners (the pipe's `activity` event) hear each entry as it is added; a failing listener is ignored."""
import threading
import time
from collections import deque

from .log import log

KINDS = ("level", "kill", "model", "info")


class Activity:
    def __init__(self, size=50, clock=None):
        self._items = deque(maxlen=size)
        self._lock = threading.Lock()
        self._clock = clock
        self._listeners = []

    def listen(self, fn):
        """fn(entry) for every entry added from now on ({"t", "kind", "text"}), on the adding thread."""
        self._listeners.append(fn)

    def add(self, kind, text):
        item = {"t": self._clock() if self._clock else time.time(), "kind": kind, "text": text}
        with self._lock:
            self._items.append(item)
        for fn in list(self._listeners):
            try:
                fn(dict(item))
            except Exception as e:
                log(f"activity listener failed: {type(e).__name__}", "warn")

    def recent(self, n=50):
        with self._lock:
            return list(self._items)[::-1][:max(0, n)]
