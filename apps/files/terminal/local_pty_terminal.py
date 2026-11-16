from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
from pathlib import Path
import shutil
import signal
import struct
import sys

# These modules only exist on POSIX systems. Keeping their imports guarded is
# essential because this backend is imported while the Windows app starts.
if os.name == "posix":
    import fcntl
    import pty
    import termios
else:  # pragma: no cover - exercised by the Windows packaged application
    fcntl = None  # type: ignore[assignment]
    pty = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]

try:
    import winpty
    from winpty import PTY, Backend
except Exception:  # pragma: no cover
    winpty = None  # type: ignore[assignment]
    PTY = None  # type: ignore[assignment]
    Backend = None  # type: ignore[assignment]

from core.result import OperationResult, result_from_exception


class LocalPtyTerminalSession:
    """Local shell backend (POSIX PTY or Windows ConPTY) for the xterm.js frontend."""

    def __init__(
        self,
        *,
        cwd: str | None = None,
        shell_path: str | None = None,
        startup_command: str | None = None,
    ) -> None:
        self.cwd = cwd
        self.shell_path = shell_path
        self.startup_command = startup_command
        self._process: asyncio.subprocess.Process | None = None
        self._master_fd: int | None = None
        self._winpty: PTY | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._on_output: Callable[[str], None] | None = None
        self._on_exit: Callable[[], None] | None = None
        self._closing = False

    async def start(self, on_output: Callable[[str], None], on_exit: Callable[[], None] | None = None) -> OperationResult:
        await self.close()
        self._on_output = on_output
        self._on_exit = on_exit
        self._closing = False

        shell = resolve_shell_path(self.shell_path)
        if shell is None:
            suggested = (
                "Set a terminal local shell path in Settings, for example powershell.exe or cmd.exe."
                if os.name == "nt"
                else "Set a terminal local shell path in Settings, for example /bin/bash or /bin/sh."
            )
            return OperationResult.failure(
                "Could not find a local shell.",
                suggested_fix=suggested,
            )

        cwd = self._valid_cwd()

        if os.name == "nt":
            return await self._start_windows(shell, cwd)
        return await self._start_posix(shell, cwd)

    async def _start_windows(self, shell: str, cwd: Path) -> OperationResult:
        if PTY is None:
            return OperationResult.failure(
                "Local embedded terminal is unavailable on Windows without pywinpty.",
                suggested_fix="Install pywinpty using 'uv add pywinpty' or 'pip install pywinpty'.",
            )
        try:
            backend = Backend.ConPTY if hasattr(Backend, "ConPTY") else Backend.WinPTY
            pty_proc = PTY(cols=80, rows=24, backend=backend)
            spawned = pty_proc.spawn(shell, cwd=str(cwd))
            if not spawned:
                return OperationResult.failure(f"Failed to spawn local shell '{shell}'.")
            self._winpty = pty_proc
            self._reader_task = asyncio.create_task(self._read_output_win32())
            startup = (self.startup_command or "").strip()
            if startup:
                await self.send(f"{startup}\r\n")
            return OperationResult.success(f"Local terminal started in {cwd}.")
        except Exception as exc:
            await self.close()
            return result_from_exception("Could not start local terminal.", exc, retryable=True)

    async def _start_posix(self, shell: str, cwd: Path) -> OperationResult:
        if pty is None:
            return OperationResult.failure("POSIX PTY is unavailable on this operating system.")
        master_fd: int | None = None
        slave_fd: int | None = None
        try:
            master_fd, slave_fd = pty.openpty()
            os.set_blocking(master_fd, False)
            self._process = await asyncio.create_subprocess_exec(
                shell,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(cwd),
                start_new_session=True,
            )
            os.close(slave_fd)
            slave_fd = None
            self._master_fd = master_fd
            self._reader_task = asyncio.create_task(self._read_output())
            startup = (self.startup_command or "").strip()
            if startup:
                await self.send(f"{startup}\r")
            return OperationResult.success(f"Local terminal started in {cwd}.")
        except Exception as exc:
            if slave_fd is not None:
                try:
                    os.close(slave_fd)
                except OSError:
                    pass
            if master_fd is not None and self._master_fd is None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
            await self.close()
            return result_from_exception("Could not start local terminal.", exc, retryable=True)

    async def send(self, text: str) -> OperationResult:
        if os.name == "nt" and self._winpty is not None:
            if not self._winpty.isalive():
                return OperationResult.failure("Local terminal session is not running.")
            try:
                self._winpty.write(text)
                return OperationResult.success("Local terminal input sent.")
            except Exception as exc:
                return result_from_exception("Could not send local terminal input.", exc, retryable=True)

        if self._master_fd is None:
            return OperationResult.failure("Local terminal session is not running.")
        data = memoryview(text.encode("utf-8", errors="replace"))
        while data:
            try:
                written = os.write(self._master_fd, data)
                data = data[written:]
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except OSError as exc:
                return result_from_exception("Could not send local terminal input.", exc, retryable=True)
        return OperationResult.success("Local terminal input sent.")

    async def interrupt(self) -> OperationResult:
        return await self.send("\x03")

    async def resize(self, columns: int, rows: int) -> OperationResult:
        if columns < 20 or rows < 5:
            return OperationResult.skipped("Ignored terminal resize below minimum size.")

        if os.name == "nt" and self._winpty is not None:
            if not self._winpty.isalive():
                return OperationResult.failure("Local terminal session is not running.")
            try:
                self._winpty.set_size(columns, rows)
                return OperationResult.success("Local terminal resized.")
            except Exception as exc:
                return result_from_exception("Could not resize local terminal.", exc, retryable=True)

        if os.name != "posix" or fcntl is None or termios is None:
            return OperationResult.failure("Local embedded terminal resize is unavailable on this operating system.")
        if self._master_fd is None:
            return OperationResult.failure("Local terminal session is not running.")
        try:
            size = struct.pack("HHHH", rows, columns, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, size)
            return OperationResult.success("Local terminal resized.")
        except OSError as exc:
            return result_from_exception("Could not resize local terminal.", exc, retryable=True)

    async def close(self) -> OperationResult:
        self._closing = True
        task = self._reader_task
        self._reader_task = None
        if task is not None:
            task.cancel()

        if self._winpty is not None:
            pty_proc = self._winpty
            self._winpty = None
            try:
                if pty_proc.isalive():
                    pty_proc.write("exit\r\n")
            except Exception:
                pass
            del pty_proc

        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            await self._terminate_process(process)

        fd = self._master_fd
        self._master_fd = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        return OperationResult.success("Local terminal session closed.")

    async def _read_output_win32(self) -> None:
        pty_proc = self._winpty
        if pty_proc is None:
            return
        try:
            while not self._closing and pty_proc is not None and pty_proc.isalive():
                try:
                    data = pty_proc.read(blocking=False)
                except Exception:
                    break
                if data and self._on_output:
                    self._on_output(data)
                await asyncio.sleep(0.015)
            # Drain any trailing output
            if pty_proc is not None:
                try:
                    data = pty_proc.read(blocking=False)
                    if data and self._on_output:
                        self._on_output(data)
                except Exception:
                    pass
        finally:
            self._winpty = None
            self._reader_task = None
            if not self._closing and self._on_exit:
                self._on_exit()

    async def _read_output(self) -> None:
        if self._master_fd is None:
            return
        fd = self._master_fd
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def readable() -> None:
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                return
            except OSError:
                data = b""
            queue.put_nowait(data)

        loop.add_reader(fd, readable)
        try:
            while True:
                data = await queue.get()
                if not data:
                    break
                if self._on_output:
                    self._on_output(data.decode("utf-8", errors="replace"))
        finally:
            try:
                loop.remove_reader(fd)
            except (OSError, RuntimeError, ValueError):
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            self._process = None
            self._reader_task = None
            self._master_fd = None
            if not self._closing and self._on_exit:
                self._on_exit()

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGHUP)
        except (ProcessLookupError, AttributeError):
            pass
        except OSError:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
            return
        except asyncio.TimeoutError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, AttributeError):
            pass
        except OSError:
            process.kill()
        await process.wait()

    def _valid_cwd(self) -> Path:
        if self.cwd:
            target = Path(self.cwd).expanduser()
            if target.is_file():
                target = target.parent
            if target.is_dir():
                return target
        return Path.home()


def resolve_shell_path(shell_path: str | None = None) -> str | None:
    if os.name == "nt":
        candidates = [
            shell_path,
            os.environ.get("SHELL"),
            shutil.which("pwsh.exe"),
            shutil.which("powershell.exe"),
            os.environ.get("COMSPEC"),
            shutil.which("cmd.exe"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.is_file():
                return str(path)
            which = shutil.which(candidate)
            if which and Path(which).is_file():
                return which
        return None

    candidates = [
        shell_path,
        os.environ.get("SHELL"),
        "/bin/bash",
        "/bin/sh",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None
