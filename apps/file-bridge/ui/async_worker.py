from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.async_runtime import AsyncRuntime
from core.result import OperationResult, result_from_exception

__all__ = ["AsyncProgressWorker", "AsyncRuntime", "AsyncWorker"]


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
