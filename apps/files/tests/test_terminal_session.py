from __future__ import annotations

import asyncio
import unittest

from core.result import OperationStatus
from terminal.terminal_bridge import normalize_terminal_paste
from terminal.ssh_terminal import SSHTerminalSession


class FakeStdin:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, text: str) -> None:
        self.writes.append(text)

    async def drain(self) -> None:
        return None


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = FakeStdin()
        self.size: tuple[int, int] | None = None
        self.stdout = None
        self.terminated = False

    def change_terminal_size(self, columns: int, rows: int) -> None:
        self.size = (columns, rows)

    def terminate(self) -> None:
        self.terminated = True


class FakeStdout:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    async def read(self, _size: int) -> str:
        await asyncio.sleep(0)
        return self.chunks.pop(0)


class TestSSHTerminalSession(unittest.TestCase):
    def test_terminal_session_sends_input_interrupt_and_resize(self) -> None:
        session = SSHTerminalSession(connection=None)
        process = FakeProcess()
        session._process = process

        asyncio.run(session.send("ls\r"))
        asyncio.run(session.interrupt())
        asyncio.run(session.resize(100, 32))

        self.assertEqual(process.stdin.writes, ["ls\r", "\x03"])
        self.assertEqual(process.size, (100, 32))

    def test_terminal_paste_normalizes_clipboard_newlines_to_carriage_returns(self) -> None:
        self.assertEqual(normalize_terminal_paste("one\ntwo\r\nthree\rfour"), "one\rtwo\rthree\rfour")

    def test_terminal_session_ignores_tiny_resize(self) -> None:
        session = SSHTerminalSession(connection=None)
        process = FakeProcess()
        session._process = process

        result = asyncio.run(session.resize(2, 30))

        self.assertEqual(result.status, OperationStatus.SKIPPED)
        self.assertIsNone(process.size)

    def test_terminal_session_builds_cwd_and_startup_command(self) -> None:
        session = SSHTerminalSession(connection=None, cwd="/var/www/site", startup_command="source ~/.profile")

        command = session._shell_command()

        self.assertEqual(command, "cd '/var/www/site'; source ~/.profile; exec \"${SHELL:-/bin/sh}\" -l")

    def test_terminal_session_notifies_when_shell_exits(self) -> None:
        session = SSHTerminalSession(connection=None)
        process = FakeProcess()
        process.stdout = FakeStdout(["hello", ""])
        session._process = process
        output: list[str] = []
        exited: list[bool] = []
        session._on_output = output.append
        session._on_exit = lambda: exited.append(True)

        asyncio.run(session._read_output())

        self.assertEqual(output, ["hello"])
        self.assertEqual(exited, [True])

    def test_terminal_session_health_check_delegates_to_connection(self) -> None:
        class Connection:
            async def health_check(self):
                from core.result import OperationResult

                return OperationResult.success("Connection is healthy.")

        result = asyncio.run(SSHTerminalSession(connection=Connection()).health_check())

        self.assertTrue(result.ok)

    def test_terminal_session_handles_connection_lost_gracefully(self) -> None:
        session = SSHTerminalSession(connection=None)

        class BrokenStdout:
            async def read(self, n: int = 4096) -> str:
                raise ConnectionResetError("Server not responding to keepalive")

        process = FakeProcess()
        process.stdout = BrokenStdout()
        session._process = process
        output: list[str] = []
        exited: list[bool] = []
        session._on_output = output.append
        session._on_exit = lambda: exited.append(True)

        # Must complete cleanly without raising unhandled exception
        asyncio.run(session._read_output())

        self.assertEqual(len(output), 1)
        self.assertIn("Connection closed", output[0])
        self.assertIn("Server not responding to keepalive", output[0])
        self.assertEqual(exited, [True])
        self.assertIsNone(session._process)

