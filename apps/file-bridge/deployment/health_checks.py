from __future__ import annotations

import asyncio
import ssl
from urllib.parse import urlsplit

from core.connections.ssh_async import sh_quote
from core.result import OperationResult
from security.secret_scanner import redact_text

from deployment.deployment_job import HealthCheckConfig, HealthCheckOrigin, HealthCheckResult


MAX_HEALTH_BODY_BYTES = 128 * 1024
REMOTE_STATUS_MARKER = "__RFM_HTTP_STATUS__"


class HealthCheckService:
    async def run(self, connection, config: HealthCheckConfig, *, cwd: str) -> OperationResult:  # type: ignore[no-untyped-def]
        if not config.enabled:
            result = HealthCheckResult(ok=True, message="No health checks configured.")
            return OperationResult.success(result.message, data=result)

        warnings: list[str] = []
        if not config.verify_tls and config.http_url.lower().startswith("https://"):
            warnings.append("TLS verification is disabled for the deployment health check.")

        command_ok: bool | None = None
        http_ok: bool | None = None
        status_code: int | None = None
        attempts_used = 0

        if config.command.strip():
            command_result = await connection.run_command(config.command.strip(), cwd=cwd)
            data = command_result.data if isinstance(command_result.data, dict) else {}
            command_ok = bool(command_result.ok and int(data.get("exit_status", 1)) == 0)
            if not command_ok:
                details = redact_text(str(data.get("stderr") or command_result.technical_details or "")).strip()
                health = HealthCheckResult(
                    ok=False,
                    message="Remote command health check failed.",
                    command_ok=False,
                    warnings=warnings,
                    technical_details=details or None,
                )
                result = OperationResult.failure(
                    health.message,
                    technical_details=health.technical_details,
                    warnings=warnings,
                    retryable=True,
                    logs=["Health check command exited with a nonzero status."],
                )
                result.data = health
                return result

        if config.http_url.strip():
            last_details: str | None = None
            for attempt in range(1, config.attempts + 1):
                attempts_used = attempt
                if config.http_origin == HealthCheckOrigin.REMOTE:
                    http_result = await self._remote_http(connection, config)
                else:
                    http_result = await self._desktop_http(config)
                if http_result.ok:
                    response = http_result.data
                    status_code = response["status_code"]
                    body = response["body"]
                    status_ok = config.minimum_status <= status_code <= config.maximum_status
                    body_ok = not config.expected_substring or config.expected_substring in body
                    if status_ok and body_ok:
                        http_ok = True
                        break
                    if not status_ok:
                        last_details = (
                            f"HTTP status {status_code} is outside "
                            f"{config.minimum_status}-{config.maximum_status}."
                        )
                    else:
                        last_details = "Expected response text was not found."
                else:
                    last_details = http_result.technical_details or http_result.message
                if attempt < config.attempts and config.interval_seconds:
                    await asyncio.sleep(config.interval_seconds)
            if not http_ok:
                health = HealthCheckResult(
                    ok=False,
                    message="HTTP health check failed.",
                    command_ok=command_ok,
                    http_ok=False,
                    status_code=status_code,
                    attempts_used=attempts_used,
                    warnings=warnings,
                    technical_details=redact_text(last_details or ""),
                )
                result = OperationResult.failure(
                    health.message,
                    technical_details=health.technical_details,
                    warnings=warnings,
                    retryable=True,
                    logs=[f"HTTP health check exhausted {attempts_used} attempt(s)."],
                )
                result.data = health
                return result

        health = HealthCheckResult(
            ok=True,
            message="Deployment health checks passed.",
            command_ok=command_ok,
            http_ok=http_ok,
            status_code=status_code,
            attempts_used=attempts_used,
            warnings=warnings,
        )
        return OperationResult.success(health.message, data=health, warnings=warnings)

    async def _desktop_http(self, config: HealthCheckConfig) -> OperationResult:
        parsed = urlsplit(config.http_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return OperationResult.failure("Health-check URL must use http:// or https://.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        context = None
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            if not config.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    parsed.hostname,
                    port,
                    ssl=context,
                    server_hostname=parsed.hostname if parsed.scheme == "https" else None,
                ),
                timeout=config.timeout_seconds,
            )
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {parsed.hostname}\r\n"
                "User-Agent: NOBADFileBridge/0.4\r\n"
                "Accept: */*\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(request.encode("ascii", errors="ignore"))
            await writer.drain()
            raw = await asyncio.wait_for(
                reader.read(MAX_HEALTH_BODY_BYTES),
                timeout=config.timeout_seconds,
            )
            writer.close()
            await writer.wait_closed()
            header, _, body = raw.partition(b"\r\n\r\n")
            first_line = header.splitlines()[0].decode("ascii", errors="replace")
            parts = first_line.split()
            if len(parts) < 2 or not parts[1].isdigit():
                return OperationResult.failure("Health-check server returned an invalid HTTP response.")
            return OperationResult.success(
                "HTTP health response received.",
                data={
                    "status_code": int(parts[1]),
                    "body": body.decode("utf-8", errors="replace"),
                },
            )
        except Exception as exc:
            return OperationResult.failure(
                "Desktop HTTP health request failed.",
                technical_details=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )

    async def _remote_http(self, connection, config: HealthCheckConfig) -> OperationResult:  # type: ignore[no-untyped-def]
        insecure = " --insecure" if not config.verify_tls else ""
        command = (
            "tmp=$(mktemp) || exit 1; "
            f"code=$(curl -sS -L{insecure} --max-time {int(config.timeout_seconds)} "
            f"-o \"$tmp\" -w '%{{http_code}}' {sh_quote(config.http_url)}); "
            "rc=$?; "
            "body=$(head -c 131072 \"$tmp\"); rm -f \"$tmp\"; "
            f"printf '%s\\n{REMOTE_STATUS_MARKER}%s' \"$body\" \"$code\"; exit \"$rc\""
        )
        result = await connection.run_command(command)
        data = result.data if isinstance(result.data, dict) else {}
        if not result.ok or int(data.get("exit_status", 1)) != 0:
            return OperationResult.failure(
                "Remote HTTP health request failed.",
                technical_details=redact_text(str(data.get("stderr") or result.technical_details or "")) or None,
                retryable=True,
            )
        stdout = str(data.get("stdout") or "")
        body, marker, status_text = stdout.rpartition(REMOTE_STATUS_MARKER)
        if not marker or not status_text.strip().isdigit():
            return OperationResult.failure(
                "Remote curl health response was invalid.",
                suggested_fix="Verify curl is installed on the remote server.",
            )
        return OperationResult.success(
            "Remote HTTP health response received.",
            data={"status_code": int(status_text.strip()), "body": body.rstrip("\n")},
        )
