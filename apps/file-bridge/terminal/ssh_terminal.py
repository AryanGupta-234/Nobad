from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any

from core.result import OperationResult, result_from_exception

logger = logging.getLogger("remote_file_manager.terminal.ssh")


class SSHTerminalSession:
    """AsyncSSH PTY session abstraction used by the xterm.js frontend."""

    def __init__(self, connection: Any, *, cwd: str | None = None, startup_command: str | None = None) -> None:
        self.connection = connection
        self.cwd = cwd
        self.startup_command = startup_command
        self._process: Any | None = None
        self._reader_task: asyncio.Task | None = None
        self._on_output: Callable[[str], None] | None = None
        self._on_exit: Callable[[], None] | None = None
        self._closing = False

    async def start(self, on_output: Callable[[str], None], on_exit: Callable[[], None] | None = None) -> OperationResult:
        if self.connection.raw_connection is None:
            return OperationResult.failure("Terminal unavailable because this connection is not open.")
        self._on_output = on_output
        self._on_exit = on_exit
        self._closing = False
        try:
            command = self._shell_command()
            self._process = await self.connection.raw_connection.create_process(command, term_type="xterm-256color")
            self._reader_task = asyncio.create_task(self._read_output())
            return OperationResult.success("Terminal session started.")
        except Exception as exc:  # pragma: no cover - network dependent
            return result_from_exception("Could not start terminal session.", exc, retryable=True)

    async def send(self, text: str) -> OperationResult:
        if self._process is None:
            return OperationResult.failure("Terminal session is not running.")
        self._process.stdin.write(text)
        await self._process.stdin.drain()
        return OperationResult.success("Terminal input sent.")

    async def interrupt(self) -> OperationResult:
        return await self.send("\x03")

    async def resize(self, columns: int, rows: int) -> OperationResult:
        if self._process is None:
            return OperationResult.failure("Terminal session is not running.")
        if columns < 20 or rows < 5:
            return OperationResult.skipped("Ignored terminal resize below minimum size.")
        self._process.change_terminal_size(columns, rows)
        return OperationResult.success("Terminal resized.")

    async def close(self) -> OperationResult:
        self._closing = True
        reader_task = self._reader_task
        self._reader_task = None
        if reader_task:
            reader_task.cancel()
        if self._process:
            self._process.terminate()
            self._process = None
        if reader_task:
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
        return OperationResult.success("Terminal session closed.")

    async def health_check(self) -> OperationResult:
        """Check the underlying SSH transport without writing to the PTY."""
        if self.connection is None:
            return OperationResult.failure("Terminal connection is unavailable.", retryable=True)
        return await self.connection.health_check()

    async def _read_output(self) -> None:
        assert self._process is not None
        try:
            while True:
                data = await self._process.stdout.read(4096)
                if not data:
                    break
                if self._on_output:
                    self._on_output(data)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Terminal read stream ended: %s", exc)
            if self._on_output and not self._closing:
                self._on_output(f"\r\n\x1b[33m[Connection closed: {exc}]\x1b[0m\r\n")
        finally:
            self._reader_task = None
            self._process = None
            if not self._closing and self._on_exit:
                self._on_exit()

    def _quote(self, value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    def _shell_command(self) -> str | None:
        startup = (self.startup_command or "").strip()
        commands: list[str] = []
        if self.cwd:
            commands.append(f"cd {self._quote(self.cwd)}")
        if startup:
            commands.append(startup)
        if not commands:
            return None
        commands.append('exec "${SHELL:-/bin/sh}" -l')
        return "; ".join(commands)
