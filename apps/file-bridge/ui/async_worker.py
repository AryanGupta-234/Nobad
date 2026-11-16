from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.result import OperationResult, result_from_exception


class AsyncWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        super().__init__()
        self._coro_factory = coro_factory

    def run(self) -> None:
        try:
            result = AsyncRuntime.instance().run(self._coro_factory())
            if isinstance(result, OperationResult) and not result.ok:
                self.failed.emit(result)
            else:
                self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(result_from_exception("Background operation failed.", exc))


class AsyncProgressWorker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, coro_factory: Callable[[Callable[[object], None]], Coroutine[Any, Any, Any]]) -> None:
        super().__init__()
        self._coro_factory = coro_factory

    def run(self) -> None:
        try:
            result = AsyncRuntime.instance().run(self._coro_factory(self.progress.emit))
            if isinstance(result, OperationResult) and not result.ok:
                self.failed.emit(result)
            else:
                self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(result_from_exception("Background operation failed.", exc))


class AsyncRuntime:
    _instance: "AsyncRuntime | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="rfm-async-runtime", daemon=True)
        self._thread.start()

    @classmethod
    def instance(cls) -> "AsyncRuntime":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                atexit.register(cls._instance.shutdown)
            return cls._instance

    def run(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result()

    def submit(self, coroutine: Coroutine[Any, Any, Any]):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def shutdown(self) -> None:
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()
