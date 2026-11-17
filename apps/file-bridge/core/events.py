"""A tiny Qt-free publish/subscribe event, so backend services don't depend on a UI toolkit.

It keeps the familiar ``connect`` / ``disconnect`` / ``emit`` shape of a Qt signal, but handlers run synchronously on
the thread that calls ``emit`` (for the transfer manager: the asyncio runtime thread). A UI that needs its own thread
re-emits from a handler (the web UI pushes onto its event bus).

A failing handler is logged and skipped: one broken subscriber must never stop a transfer."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")
logger = logging.getLogger("remote_file_manager.events")


class Event(Generic[T]):
    def __init__(self, name: str = "event") -> None:
        self.name = name
        self._handlers: list[Callable[[T], object]] = []
        self._lock = threading.Lock()

    def connect(self, handler: Callable[[T], object]) -> Callable[[T], object]:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)
        return handler

    def disconnect(self, handler: Callable[[T], object]) -> None:
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)

    def emit(self, value: T) -> None:
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler(value)
            except Exception:
                logger.exception("Handler for %s failed", self.name)

    def __len__(self) -> int:
        with self._lock:
            return len(self._handlers)
