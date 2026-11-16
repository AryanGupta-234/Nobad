from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from core.result import OperationResult


class TerminalSessionBackend(Protocol):
    async def start(self, on_output: Callable[[str], None], on_exit: Callable[[], None] | None = None) -> OperationResult:
        """Start the terminal session and stream output to the callback."""
        ...

    async def send(self, text: str) -> OperationResult:
        """Send raw terminal input."""
        ...

    async def interrupt(self) -> OperationResult:
        """Send Ctrl+C or the backend equivalent."""
        ...

    async def resize(self, columns: int, rows: int) -> OperationResult:
        """Resize the PTY/terminal."""
        ...

    async def close(self) -> OperationResult:
        """Close the terminal session."""
        ...
