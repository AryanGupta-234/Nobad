from __future__ import annotations

import ssl
from typing import Any

from core.connections.base import BaseConnection
from core.connections.capabilities import ConnectionCapabilities
from core.result import OperationResult, result_from_exception

try:
    import aioftp
except ImportError:  # pragma: no cover - dependency is optional for unit tests
    aioftp = None  # type: ignore[assignment]


class FTPConnection(BaseConnection):
    def __init__(self, profile, *, secure: bool = False) -> None:  # type: ignore[no-untyped-def]
        super().__init__(profile)
        self.secure = secure
        self._client: Any | None = None
        self.capabilities = ConnectionCapabilities.ftp(secure=secure)

    async def connect(self, *, password: str | None = None, passphrase: str | None = None) -> OperationResult:
        del passphrase
        if aioftp is None:
            return OperationResult.failure(
                "aioftp is not installed.",
                suggested_fix="Install dependencies with pip install -e .",
            )
        options = self.profile.connection_options
        timeout = options.timeout
        tls_mode = options.tls_mode if self.secure else "none"
        verify_tls = options.verify_tls
        ssl_context = self._ssl_context(verify_tls) if self.secure else None
        try:
            client_options: dict[str, object] = {
                "socket_timeout": timeout,
                "connection_timeout": timeout,
                "path_timeout": timeout,
                "encoding": options.encoding,
            }
            if self.secure and tls_mode == "implicit":
                client_options["ssl"] = ssl_context
            self._client = aioftp.Client(**client_options)
            await self._client.connect(self.profile.host, self.profile.port)
            if self.secure and tls_mode != "implicit":
                await self._client.upgrade_to_tls(ssl_context)
            await self._client.login(self.profile.username, password or "")
            warnings: list[str] = []
            if not self.secure:
                warnings.append("FTP sends credentials and data without transport encryption.")
            elif not verify_tls:
                warnings.append("FTPS certificate verification is disabled for this session.")
            return OperationResult.success(
                f"Connected to {self.profile.host}.",
                data=self,
                warnings=warnings,
            )
        except Exception as exc:  # pragma: no cover - network dependent
            self._client = None
            return result_from_exception(
                f"Could not connect to {self.profile.host}:{self.profile.port}.",
                exc,
                retryable=True,
            )

    async def disconnect(self) -> OperationResult:
        if self._client is None:
            return OperationResult.skipped("Connection is already closed.")
        try:
            await self._client.quit()
        except Exception:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        return OperationResult.success(f"Disconnected from {self.profile.host}.")

    async def health_check(self) -> OperationResult:
        if self._client is None:
            return OperationResult.failure("Connection is not open.", retryable=True)
        try:
            await self._client.get_current_directory()
            return OperationResult.success("Connection is healthy.")
        except Exception as exc:
            return result_from_exception("Connection health check failed.", exc, retryable=True)

    def file_operations(self):
        from file_ops.ftp_ops import FTPFileOperations

        if self._client is None:
            raise RuntimeError("FTP client is not connected.")
        return FTPFileOperations(self._client)

    def _ssl_context(self, verify: bool) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if not verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context
