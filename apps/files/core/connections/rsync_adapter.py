from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import signal
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from core.result import OperationResult, result_from_exception
from core.connections.profile import AuthType, ProtocolType


class RsyncDirection(StrEnum):
    LOCAL_TO_REMOTE = "local_to_remote"
    REMOTE_TO_LOCAL = "remote_to_local"
    REMOTE_PUSH = "remote_push"
    REMOTE_PULL = "remote_pull"


@dataclass(frozen=True, slots=True)
class RsyncProbe:
    available: bool
    executable: str | None = None
    version: str | None = None
    reason: str = ""


class RsyncAdapter:
    def __init__(self, executable: str | None = None) -> None:
        self.configured_executable = executable

    async def probe_local(self) -> RsyncProbe:
        executable = self.configured_executable or shutil.which("rsync")
        if not executable:
            return RsyncProbe(False, reason="rsync was not found in settings or PATH.")
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                return RsyncProbe(False, executable, reason=stderr.decode(errors="replace").strip())
            first_line = stdout.decode(errors="replace").splitlines()[0] if stdout else ""
            return RsyncProbe(True, executable, first_line)
        except Exception as exc:
            return RsyncProbe(False, executable, reason=str(exc))

    async def probe_remote(self, connection) -> OperationResult:  # type: ignore[no-untyped-def]
        if not connection.capabilities.can_exec_command:
            return OperationResult.failure("Remote rsync requires SSH command capability.")
        result = await connection.run_command("command -v rsync && rsync --version | head -n 1")
        if not result.ok or result.data.get("exit_status") != 0:
            return OperationResult.failure("rsync is not available on the remote server.")
        return OperationResult.success("Remote rsync is available.", data=result.data["stdout"].strip())

    async def probe_server_auth(self, initiating_connection, target_profile) -> OperationResult:  # type: ignore[no-untyped-def]
        target = f"{target_profile.username}@{target_profile.host}"
        command = (
            "ssh -o BatchMode=yes -o ConnectTimeout=8 "
            f"-p {int(target_profile.port)} {shlex.quote(target)} true"
        )
        result = await initiating_connection.run_command(command)
        if not result.ok or result.data.get("exit_status") != 0:
            return OperationResult.failure(
                "Server-to-server SSH authentication is not configured.",
                suggested_fix="Use local relay or configure non-interactive SSH trust between the servers.",
            )
        return OperationResult.success("Server-to-server SSH authentication is available.")

    async def run_local(
        self,
        *,
        source: str,
        destination: str,
        delete: bool = False,
        destructive_confirmed: bool = False,
        progress_callback: Callable[[float], None] | None = None,
        extra_args: list[str] | None = None,
    ) -> OperationResult:
        if delete and not destructive_confirmed:
            return OperationResult.failure("rsync --delete requires explicit destructive confirmation.")
        probe = await self.probe_local()
        if not probe.available or not probe.executable:
            return OperationResult.failure("rsync is unavailable.", technical_details=probe.reason)
        command = [probe.executable, "-a", "--info=progress2", "--protect-args"]
        if delete:
            command.append("--delete")
        command.extend(extra_args or [])
        command.extend(["--", source, destination])
        return await self._run_process(command, progress_callback)

    async def run_profile_transfer(
        self,
        *,
        profile,
        local_path: str,
        remote_path: str,
        direction: RsyncDirection,
        delete: bool = False,
        destructive_confirmed: bool = False,
        exclude_patterns: list[str] | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> OperationResult:  # type: ignore[no-untyped-def]
        if profile.protocol not in {ProtocolType.SSH, ProtocolType.SFTP}:
            return OperationResult.failure("Local rsync acceleration requires an SSH/SFTP profile.")
        if profile.auth_type == AuthType.PASSWORD:
            return OperationResult.failure(
                "Local rsync cannot use the app's stored password non-interactively.",
                suggested_fix="Use SSH agent/key authentication or the normal SFTP transfer queue.",
            )
        if delete and not destructive_confirmed:
            return OperationResult.failure("rsync --delete requires explicit destructive confirmation.")
        probe = await self.probe_local()
        if not probe.available or not probe.executable:
            return OperationResult.failure("rsync is unavailable.", technical_details=probe.reason)
        ssh_parts = ["ssh", "-o", "BatchMode=yes", "-p", str(int(profile.port))]
        if profile.auth_type == AuthType.SSH_KEY and profile.ssh_private_key_path:
            ssh_parts.extend(["-i", profile.ssh_private_key_path])
        command = [
            probe.executable,
            "-a",
            "--info=progress2",
            "--protect-args",
            "-e",
            " ".join(shlex.quote(value) for value in ssh_parts),
        ]
        if delete:
            command.append("--delete")
        for pattern in exclude_patterns or []:
            command.extend(["--exclude", pattern])
        remote = f"{profile.username}@{profile.host}:{remote_path}"
        if direction == RsyncDirection.LOCAL_TO_REMOTE:
            command.extend(["--", local_path, remote])
        elif direction == RsyncDirection.REMOTE_TO_LOCAL:
            command.extend(["--", remote, local_path])
        else:
            return OperationResult.failure("Unsupported local rsync direction.")
        return await self._run_process(command, progress_callback)

    async def _run_process(
        self,
        command: list[str],
        progress_callback: Callable[[float], None] | None,
    ) -> OperationResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
            assert process.stdout is not None
            output: list[str] = []
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace")
                output.append(text)
                match = re.search(r"(\d{1,3})%", text)
                if match and progress_callback:
                    progress_callback(min(100.0, float(match.group(1))))
            stderr = (await process.stderr.read()).decode(errors="replace") if process.stderr else ""
            return_code = await process.wait()
            if return_code != 0:
                return OperationResult.failure(
                    f"rsync exited with status {return_code}.",
                    technical_details=stderr[-4096:],
                    retryable=True,
                )
            if progress_callback:
                progress_callback(100.0)
            return OperationResult.success("rsync transfer completed.")
        except asyncio.CancelledError:
            if "process" in locals() and process.returncode is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                await process.wait()
            raise
        except Exception as exc:
            return result_from_exception("Could not run rsync.", exc, retryable=True)

    def build_remote_command(
        self,
        *,
        source_path: str,
        destination_profile,
        destination_path: str,
        direction: RsyncDirection,
        delete: bool = False,
    ) -> str:  # type: ignore[no-untyped-def]
        target = f"{destination_profile.username}@{destination_profile.host}"
        ssh_command = f"ssh -p {int(destination_profile.port)}"
        options = ["rsync", "-a", "--protect-args", "-e", ssh_command]
        if delete:
            options.append("--delete")
        remote = f"{target}:{destination_path}"
        if direction == RsyncDirection.REMOTE_PUSH:
            options.extend(["--", source_path, remote])
        elif direction == RsyncDirection.REMOTE_PULL:
            options.extend(["--", remote, source_path])
        else:
            raise ValueError("Remote command requires REMOTE_PUSH or REMOTE_PULL.")
        return " ".join(shlex.quote(value) for value in options)
