from __future__ import annotations

from abc import ABC, abstractmethod

from core.connections.capabilities import ConnectionCapabilities
from core.connections.profile import ConnectionProfile
from core.result import OperationResult
from file_ops.remote import RemoteFileOperations


class BaseConnection(ABC):
    def __init__(self, profile: ConnectionProfile) -> None:
        self.profile = profile
        self.capabilities = ConnectionCapabilities.unsupported()

    @abstractmethod
    async def connect(self, *, password: str | None = None, passphrase: str | None = None) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> OperationResult:
        raise NotImplementedError

    def file_operations(self) -> RemoteFileOperations:
        raise RuntimeError(f"{type(self).__name__} does not provide remote file operations.")
