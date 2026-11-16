"""Long-running work for the web UI, on the shared asyncio runtime.

Same contract as NOBAD VPN's ``syscmd.run_once``: the API call returns ``{"ok": true}`` at once (or "already
running"), the work reports through its own events, and **always** finishes with ``task_done {key, error}`` so the
page can reset the button that started it, even if the work crashed."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from app_web import bus
from core.async_runtime import AsyncRuntime

_running: set[str] = set()
_lock = threading.Lock()


def is_running(key: str) -> bool:
    with _lock:
        return key in _running


def run_task(
    key: str,
    work: Callable[[], Coroutine[Any, Any, Any]],
    *,
    on_result: Callable[[Any], None] | None = None,
    runtime: AsyncRuntime | None = None,
) -> bool:
    """Start ``work()`` unless a task with the same key is already running. Returns False when it is."""
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    async def wrapper() -> None:
        error: str | None = None
        try:
            result = await work()
            if on_result is not None:
                on_result(result)
        except asyncio.CancelledError:
            error = "Cancelled."
        except Exception as exc:  # reported to the page, never raised into the runtime
            error = bus.scrub(exc) or exc.__class__.__name__
        finally:
            with _lock:
                _running.discard(key)
            bus.broadcast("task_done", {"key": key, "error": error})

    (runtime or AsyncRuntime.instance()).submit(wrapper())
    return True
