from __future__ import annotations

from core.result import OperationResult


class CommandRunner:
    def __init__(self, connection) -> None:  # type: ignore[no-untyped-def]
        self.connection = connection

    async def run(self, command: str, *, cwd: str | None = None) -> OperationResult:
        if not self.connection.capabilities.can_exec_command:
            return OperationResult.failure("Terminal unavailable because this connection does not provide SSH shell access.")
        return await self.connection.run_command(command, cwd=cwd)

