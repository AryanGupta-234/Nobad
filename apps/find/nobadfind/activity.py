"""A small in-memory log of recent governor decisions, for the UI. Never stored."""
import threading
import time
from collections import deque

KINDS = ("level", "kill", "model", "info")


class Activity:
    def __init__(self, size=50):
        self._items = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, kind, text):
        with self._lock:
            self._items.append({"t": time.time(), "kind": kind, "text": text})

    def recent(self, n=50):
        with self._lock:
            return list(self._items)[::-1][:max(0, n)]
