from __future__ import annotations

from core.result import OperationResult


class EncryptedVault:
    def store(self, *_args, **_kwargs) -> OperationResult:  # type: ignore[no-untyped-def]
        return OperationResult.failure("Encrypted vault backend is planned as a fallback to OS keyring.")

