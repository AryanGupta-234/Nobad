from __future__ import annotations

import errno
import socket
from dataclasses import dataclass
from typing import Any

from core.connections.base import BaseConnection
from core.connections.capabilities import ConnectionCapabilities
from core.result import OperationResult, result_from_exception
from security.known_hosts import default_known_hosts_path, openssh_known_hosts_path

try:
    import asyncssh
except ImportError:  # pragma: no cover - dependency is optional for unit tests
    asyncssh = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class HostKeyPrompt:
    host: str
    address: str
    port: int
    algorithm: str
    fingerprint: str
    public_key: str
    changed: bool = False
    previous_fingerprints: tuple[str, ...] = ()


def _empty_known_hosts() -> tuple[tuple, tuple, tuple, tuple, tuple, tuple, tuple]:
    return ((), (), (), (), (), (), ())


def _known_hosts_lookup(host: str, address: str, port: int):
    """Prefer app trust decisions, then fall back to the user's OpenSSH file."""
    if asyncssh is None:
        return _empty_known_hosts()

    try:
        app_path = default_known_hosts_path()
        app_matches = asyncssh.match_known_hosts(str(app_path), host, address, port)
        if any(app_matches):
            return app_matches
    except (OSError, ValueError):
        pass

    openssh_path = openssh_known_hosts_path()
    if openssh_path.is_file():
        try:
            return asyncssh.match_known_hosts(str(openssh_path), host, address, port)
        except (OSError, ValueError):
            pass
    return _empty_known_hosts()


class _HostKeyVerifier(asyncssh.SSHClient if asyncssh is not None else object):  # type: ignore[misc]
    def __init__(self) -> None:
        self.prompt: HostKeyPrompt | None = None

    def validate_host_public_key(self, host: str, address: str, port: int, key) -> bool:  # type: ignore[no-untyped-def]
        matches = _known_hosts_lookup(host, address, port)
        previous_keys = tuple(matches[0]) + tuple(matches[2])
        previous_fingerprints = tuple(
            candidate.get_fingerprint("sha256") for candidate in previous_keys
        )
        self.prompt = HostKeyPrompt(
            host=host,
            address=address,
            port=port,
            algorithm=key.get_algorithm(),
            fingerprint=key.get_fingerprint("sha256"),
            public_key=key.export_public_key("openssh").decode("ascii").strip(),
            changed=bool(previous_keys or matches[1]),
            previous_fingerprints=previous_fingerprints,
        )
        return False


class SSHConnection(BaseConnection):
    def __init__(self, profile) -> None:  # type: ignore[no-untyped-def]
        super().__init__(profile)
        self._connection: Any | None = None
        self._sftp: Any | None = None

    @property
    def raw_connection(self) -> Any | None:
        return self._connection

    @property
    def sftp_client(self) -> Any | None:
        return self._sftp

    async def connect(self, *, password: str | None = None, passphrase: str | None = None) -> OperationResult:
        if asyncssh is None:
            return OperationResult.failure(
                "AsyncSSH is not installed.",
                suggested_fix="Install dependencies with pip install -e .",
            )

        try:
            options = dict(self.profile.options or {})
            keepalive_interval = int(options.get("keepalive_interval", 30))
            keepalive_count_max = int(options.get("keepalive_count_max", 5))

            client_keys = [self.profile.ssh_private_key_path] if self.profile.ssh_private_key_path else None
            verifier = _HostKeyVerifier()
            self._connection = await asyncssh.connect(
                self.profile.host,
                port=self.profile.port,
                username=self.profile.username,
                password=password,
                client_keys=client_keys,
                passphrase=passphrase,
                known_hosts=_known_hosts_lookup,
                client_factory=lambda: verifier,
                keepalive_interval=keepalive_interval if keepalive_interval > 0 else None,
                keepalive_count_max=keepalive_count_max if keepalive_interval > 0 else None,
            )
            self._sftp = await self._connection.start_sftp_client()
            self.capabilities = ConnectionCapabilities.sftp(has_shell=True)
            return OperationResult.success(
                f"Connected to {self.profile.host}.",
                data=self,
                warnings=["SSH host keys are verified against OpenSSH/app known_hosts files."],
            )
        except Exception as exc:  # pragma: no cover - network dependent
            if verifier.prompt is not None:
                prompt = verifier.prompt
                if prompt.changed:
                    return OperationResult.failure(
                        f"SSH host fingerprint changed for {prompt.host}:{prompt.port}.",
                        data=prompt,
                        technical_details=f"{type(exc).__name__}: {exc}",
                        suggested_fix=(
                            "Do not continue until the new SHA-256 fingerprint is verified with the server "
                            "administrator or hosting provider."
                        ),
                    )
                return OperationResult.failure(
                    f"SSH host authenticity is not yet trusted for {prompt.host}:{prompt.port}.",
                    data=prompt,
                    technical_details=f"{type(exc).__name__}: {exc}",
                    suggested_fix=(
                        "Verify the SHA-256 fingerprint with the server administrator or hosting provider, "
                        "then approve it in the app."
                    ),
                )
            return classify_connect_error(self.profile.host, self.profile.port, exc)

    async def disconnect(self) -> OperationResult:
        if self._connection is None:
            return OperationResult.skipped("Connection is already closed.")
        self._connection.close()
        try:
            await self._connection.wait_closed()
        finally:
            self._connection = None
            self._sftp = None
            self.capabilities = ConnectionCapabilities.unsupported()
        return OperationResult.success(f"Disconnected from {self.profile.host}.")

    async def health_check(self) -> OperationResult:
        if self._connection is None:
            return OperationResult.failure("Connection is not open.", retryable=True)
        try:
            result = await self._connection.run("pwd", check=False)
            return OperationResult.success("Connection is healthy.", data=result.stdout.strip())
        except Exception as exc:  # pragma: no cover - network dependent
            return result_from_exception("Connection health check failed.", exc, retryable=True)

    async def run_command(self, command: str, *, cwd: str | None = None) -> OperationResult:
        if self._connection is None:
            return OperationResult.failure("Terminal unavailable because this connection is not open.")
        shell_command = f"cd {sh_quote(cwd)} && {command}" if cwd else command
        try:
            completed = await self._connection.run(shell_command, check=False)
            status = "completed" if completed.exit_status == 0 else f"exited with {completed.exit_status}"
            return OperationResult.success(
                f"Command {status}.",
                data={
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "exit_status": completed.exit_status,
                },
            )
        except Exception as exc:  # pragma: no cover - network dependent
            return result_from_exception("Remote command failed.", exc, retryable=True)

    def file_operations(self):
        from file_ops.sftp_ops import SFTPFileOperations

        if self._sftp is None:
            raise RuntimeError("SFTP client is not connected.")
        return SFTPFileOperations(self._sftp)


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def classify_connect_error(host: str, port: int, exc: BaseException) -> OperationResult:
    technical_details = f"{type(exc).__name__}: {exc}"
    message = f"Could not connect to {host}:{port}."
    text = str(exc).lower()

    if isinstance(exc, ConnectionRefusedError) or getattr(exc, "errno", None) == errno.ECONNREFUSED:
        return OperationResult.failure(
            f"SSH/SFTP connection was refused on {host}:{port}.",
            technical_details=technical_details,
            retryable=True,
            suggested_fix=(
                "Verify the SSH service is enabled, the port is correct, and the firewall/security group allows inbound "
                f"TCP {port}. Many shared hosts use a non-standard SSH port or require SSH to be enabled in the control panel."
            ),
        )

    if isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text:
        return OperationResult.failure(
            f"SSH/SFTP connection to {host}:{port} timed out.",
            technical_details=technical_details,
            retryable=True,
            suggested_fix=(
                "Check that the server is online and reachable from this network, then confirm firewall, NAT, or cloud "
                f"security-group rules allow TCP {port}."
            ),
        )

    if isinstance(exc, socket.gaierror) or "name or service not known" in text or "temporary failure in name resolution" in text:
        return OperationResult.failure(
            f"Could not resolve host {host}.",
            technical_details=technical_details,
            retryable=True,
            suggested_fix="Check the hostname/IP address and DNS/network connectivity.",
        )

    if "host key" in text or "known_hosts" in text or "known hosts" in text:
        return OperationResult.failure(
            f"SSH host key verification failed for {host}:{port}.",
            technical_details=technical_details,
            retryable=False,
            suggested_fix=(
                "Verify the server fingerprint with the hosting provider. Unknown fingerprints can be approved "
                "inside the app; changed fingerprints must be investigated before replacing them."
            ),
        )

    if "permission denied" in text or "authentication failed" in text or "login failed" in text:
        return OperationResult.failure(
            f"Authentication failed for {host}:{port}.",
            technical_details=technical_details,
            retryable=True,
            suggested_fix="Check username, password, SSH key path, key passphrase, and whether the account has SSH/SFTP access.",
        )

    return result_from_exception(message, exc, retryable=True)
