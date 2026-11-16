from __future__ import annotations

from core.connections.capabilities import ConnectionCapabilities
from core.result import OperationResult


class CPanelAdapter:
    capabilities = ConnectionCapabilities.unsupported()

    async def connect(self) -> OperationResult:
        return OperationResult.failure(
            "cPanel support requires SSH/SFTP or a compatible provider API and is planned for Phase 3."
        )

