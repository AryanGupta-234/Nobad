from __future__ import annotations

from core.connections.capabilities import ConnectionCapabilities
from core.result import OperationResult


class RcloneAdapter:
    capabilities = ConnectionCapabilities.rclone()

    async def list_remotes(self) -> OperationResult:
        return OperationResult.failure("rclone adapter is planned for Phase 3.")

