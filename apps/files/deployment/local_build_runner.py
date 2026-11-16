from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable
from pathlib import Path

from core.result import OperationResult
from security.secret_scanner import redact_text


class LocalBuildRunner:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None

    async def run(
        self,
        command: str,
        *,
        working_directory: str | Path,
        on_output: Callable[[str], None] | None = None,
    ) -> OperationResult:
        cwd = Path(working_directory).expanduser()
        if not command.strip():
            return OperationResult.skipped("Local build is disabled or has no command.")
        if not cwd.exists() or not cwd.is_dir():
            return OperationResult.failure("Local build working directory does not exist.")

        try:
            self._process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
            assert self._process.stdout is not None
            async for raw_line in self._process.stdout:
                line = redact_text(raw_line.decode("utf-8", errors="replace").rstrip())
                if on_output and line:
                    on_output(line)
            exit_status = await self._process.wait()
            if exit_status != 0:
                return OperationResult.failure(
                    f"Local build exited with status {exit_status}.",
                    suggested_fix="Fix the build command or project errors before deploying.",
                )
            return OperationResult.success("Local build completed.")
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except Exception as exc:
            return OperationResult.failure(
                "Could not run local build.",
                technical_details=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._process = None

    async def cancel(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
