from __future__ import annotations

from dataclasses import dataclass, field

from core.connections.profile import ConnectionProfile, ProtocolType
from core.connections.base import BaseConnection
from core.connections.ftp_client import FTPConnection
from core.connections.ftps_client import FTPSConnection
from core.connections.ssh_async import SSHConnection
from core.result import OperationResult


@dataclass
class ConnectionManager:
    active_connections: dict[str, BaseConnection] = field(default_factory=dict)

    async def connect_profile(
        self,
        profile: ConnectionProfile,
        *,
        password: str | None = None,
        passphrase: str | None = None,
    ) -> OperationResult:
        connection_types: dict[ProtocolType, type[BaseConnection]] = {
            ProtocolType.SFTP: SSHConnection,
            ProtocolType.SSH: SSHConnection,
            ProtocolType.FTP: FTPConnection,
            ProtocolType.FTPS: FTPSConnection,
        }
        connection_type = connection_types.get(profile.protocol)
        if connection_type is None:
            return OperationResult.failure(
                f"{profile.protocol.value.upper()} is not implemented.",
                suggested_fix="Use an SSH/SFTP/FTP/FTPS profile.",
            )

        connection = connection_type(profile)
        result = await connection.connect(password=password, passphrase=passphrase)
        if result.ok:
            self.active_connections[profile.id] = connection
            result.data = connection
        return result

    async def disconnect(self, profile_id: str) -> OperationResult:
        connection = self.active_connections.pop(profile_id, None)
        if connection is None:
            return OperationResult.skipped("Connection was not active.")
        return await connection.disconnect()

    def get(self, profile_id: str) -> BaseConnection | None:
        return self.active_connections.get(profile_id)
