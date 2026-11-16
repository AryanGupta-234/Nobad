from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from core.result import OperationResult

try:
    import keyring
except ImportError:  # pragma: no cover - dependency may not be installed in tests
    keyring = None  # type: ignore[assignment]


class SecretKind(StrEnum):
    PASSWORD = "password"
    KEY_PASSPHRASE = "key_passphrase"
    TOKEN = "token"


@dataclass(frozen=True, slots=True)
class SecureSecretReference:
    id: str
    service_name: str
    account_name: str
    kind: SecretKind


class CredentialStore:
    def __init__(self, service_prefix: str = "remote-file-manager") -> None:
        self.service_prefix = service_prefix

    def store_secret(self, profile_id: str, kind: SecretKind, secret: str) -> OperationResult:
        if keyring is None:
            return OperationResult.failure(
                "OS keyring is unavailable.",
                suggested_fix="Install keyring or configure an encrypted vault backend.",
            )
        ref_id = str(uuid4())
        service = f"{self.service_prefix}:{kind.value}"
        account = f"{profile_id}:{ref_id}"
        try:
            keyring.set_password(service, account, secret)
            return OperationResult.success(
                "Secret stored in OS keyring.",
                data=SecureSecretReference(ref_id, service, account, kind),
            )
        except Exception as exc:
            return OperationResult.failure("Could not store secret.", technical_details=f"{type(exc).__name__}: {exc}")

    def get_secret(self, reference: SecureSecretReference) -> OperationResult:
        if keyring is None:
            return OperationResult.failure("OS keyring is unavailable.")
        try:
            secret = keyring.get_password(reference.service_name, reference.account_name)
            if secret is None:
                return OperationResult.failure("Secret reference was not found.")
            return OperationResult.success("Secret loaded.", data=secret)
        except Exception as exc:
            return OperationResult.failure("Could not load secret.", technical_details=f"{type(exc).__name__}: {exc}")

    def delete_secret(self, reference: SecureSecretReference) -> OperationResult:
        if keyring is None:
            return OperationResult.failure("OS keyring is unavailable.")
        try:
            keyring.delete_password(reference.service_name, reference.account_name)
            return OperationResult.success("Secret deleted.")
        except Exception as exc:
            return OperationResult.failure("Could not delete secret.", technical_details=f"{type(exc).__name__}: {exc}")


class InMemoryCredentialStore:
    """Test-only store. Production paths should use CredentialStore."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def store_secret(self, profile_id: str, kind: SecretKind, secret: str) -> OperationResult:
        ref = SecureSecretReference(str(uuid4()), "memory", f"{profile_id}:{kind.value}", kind)
        self._values[ref.id] = secret
        return OperationResult.success("Secret stored in memory.", data=ref)

    def get_secret(self, reference: SecureSecretReference) -> OperationResult:
        value = self._values.get(reference.id)
        if value is None:
            return OperationResult.failure("Secret reference was not found.")
        return OperationResult.success("Secret loaded.", data=value)

    def delete_secret(self, reference: SecureSecretReference) -> OperationResult:
        self._values.pop(reference.id, None)
        return OperationResult.success("Secret deleted.")
