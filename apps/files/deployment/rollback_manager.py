from __future__ import annotations

from core.result import OperationResult


class RollbackManager:
    async def rollback(self, *_args, **_kwargs) -> OperationResult:  # type: ignore[no-untyped-def]
        return OperationResult.failure("Deployment rollback is planned for Phase 4.")

