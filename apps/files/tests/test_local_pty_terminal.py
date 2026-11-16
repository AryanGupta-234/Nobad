from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat
import struct
from unittest.mock import MagicMock

import pytest

from core.result import OperationStatus
from terminal.local_pty_terminal import LocalPtyTerminalSession, resolve_shell_path


def test_resolve_shell_path_prefers_explicit_executable(tmp_path, monkeypatch) -> None:
    shell = tmp_path / ("shell.bat" if os.name == "nt" else "shell")
    shell.write_text("#!/bin/sh\n" if os.name != "nt" else "@echo off\n", encoding="utf-8")
    if os.name != "nt":
        shell.chmod(shell.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("SHELL", "/missing-shell")

    assert resolve_shell_path(str(shell)) == str(shell)


def test_resolve_shell_path_uses_environment_shell(tmp_path, monkeypatch) -> None:
    shell = tmp_path / ("env-shell.bat" if os.name == "nt" else "env-shell")
    shell.write_text("#!/bin/sh\n" if os.name != "nt" else "@echo off\n", encoding="utf-8")
    if os.name != "nt":
        shell.chmod(shell.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("SHELL", str(shell))

    assert resolve_shell_path(None) == str(shell)


@pytest.mark.skipif(os.name == "nt", reason="POSIX pipe test")
@pytest.mark.asyncio
async def test_local_terminal_sends_raw_input_and_interrupt() -> None:
    read_fd, write_fd = os.pipe()
    session = LocalPtyTerminalSession()
    session._master_fd = write_fd
    try:
        await session.send("abc")
        await session.interrupt()
        os.close(write_fd)
        write_fd = -1
        assert os.read(read_fd, 4) == b"abc\x03"
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX fcntl ioctl test")
@pytest.mark.asyncio
async def test_local_terminal_resize_uses_pty_winsize(monkeypatch) -> None:
    calls: list[tuple[int, int, bytes]] = []

    def fake_ioctl(fd: int, request: int, payload: bytes) -> None:
        calls.append((fd, request, payload))

    monkeypatch.setattr("terminal.local_pty_terminal.fcntl.ioctl", fake_ioctl)
    session = LocalPtyTerminalSession()
    session._master_fd = 123

    result = await session.resize(100, 32)

    assert result.ok
    assert calls
    rows, columns, x_pixels, y_pixels = struct.unpack("HHHH", calls[0][2])
    assert (columns, rows, x_pixels, y_pixels) == (100, 32, 0, 0)


@pytest.mark.asyncio
async def test_local_terminal_resize_ignores_tiny_sizes() -> None:
    session = LocalPtyTerminalSession()
    session._master_fd = 123
    mock_winpty = MagicMock()
    mock_winpty.isalive.return_value = True
    session._winpty = mock_winpty

    result = await session.resize(10, 4)

    assert result.status == OperationStatus.SKIPPED
    mock_winpty.set_size.assert_not_called()


@pytest.mark.skipif(os.name == "nt", reason="POSIX pipe test")
@pytest.mark.asyncio
async def test_local_terminal_notifies_when_pty_closes() -> None:
    read_fd, write_fd = os.pipe()
    session = LocalPtyTerminalSession()
    session._master_fd = read_fd
    output: list[str] = []
    exited: list[bool] = []
    session._on_output = output.append
    session._on_exit = lambda: exited.append(True)

    reader = asyncio.create_task(session._read_output())
    await asyncio.sleep(0)
    os.write(write_fd, b"done")
    os.close(write_fd)
    await reader

    assert output == ["done"]
    assert exited == [True]


@pytest.mark.skipif(os.name != "nt", reason="Windows winpty test")
@pytest.mark.asyncio
async def test_local_terminal_windows_send_and_resize() -> None:
    session = LocalPtyTerminalSession()
    mock_pty = MagicMock()
    mock_pty.isalive.return_value = True
    session._winpty = mock_pty

    send_res = await session.send("echo test\r\n")
    assert send_res.ok
    mock_pty.write.assert_called_once_with("echo test\r\n")

    resize_res = await session.resize(120, 40)
    assert resize_res.ok
    mock_pty.set_size.assert_called_once_with(120, 40)

    interrupt_res = await session.interrupt()
    assert interrupt_res.ok
    mock_pty.write.assert_called_with("\x03")


@pytest.mark.skipif(os.name != "nt", reason="Windows shell resolution")
def test_resolve_shell_path_windows_default() -> None:
    resolved = resolve_shell_path(None)
    assert resolved is not None
    assert Path(resolved).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows live PTY test")
@pytest.mark.asyncio
async def test_local_terminal_windows_live_session() -> None:
    import shutil
    cmd_shell = shutil.which("cmd.exe")
    session = LocalPtyTerminalSession(shell_path=cmd_shell)
    received_output: list[str] = []
    exited = False

    def on_output(data: str) -> None:
        received_output.append(data)

    def on_exit() -> None:
        nonlocal exited
        exited = True

    start_res = await session.start(on_output, on_exit)
    assert start_res.ok
    assert session._winpty is not None

    # Wait briefly for shell prompt
    await asyncio.sleep(0.3)
    assert len(received_output) > 0

    # Test send command
    send_res = await session.send("echo TEST_WINDOWS_LOCAL_TERMINAL\r\n")
    assert send_res.ok

    found = False
    for _ in range(25):
        await asyncio.sleep(0.1)
        if "TEST_WINDOWS_LOCAL_TERMINAL" in "".join(received_output):
            found = True
            break
    assert found, f"Expected output not found in: {''.join(received_output)!r}"

    # Test resize
    resize_res = await session.resize(100, 30)
    assert resize_res.ok

    # Test close
    close_res = await session.close()
    assert close_res.ok
    assert session._winpty is None
