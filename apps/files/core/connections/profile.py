from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from core.connections.options import ConnectionOptions


class ProfileType(StrEnum):
    GENERIC_SSH_SFTP = "generic_ssh_sftp"
    FTP = "ftp"
    FTPS = "ftps"
    UBUNTU_VPS = "ubuntu_vps"
    AWS_EC2 = "aws_ec2"
    CPANEL = "cpanel"
    HPANEL = "hpanel"
    SHARED_HOSTING = "shared_hosting"
    RCLONE_REMOTE = "rclone_remote"
    S3_COMPATIBLE = "s3_compatible"
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    DROPBOX = "dropbox"


class ProtocolType(StrEnum):
    SSH = "ssh"
    SFTP = "sftp"
    FTP = "ftp"
    FTPS = "ftps"
    RCLONE = "rclone"
    API = "api"


class AuthType(StrEnum):
    PASSWORD = "password"
    SSH_KEY = "ssh_key"
    SSH_AGENT = "ssh_agent"
    TOKEN = "token"


@dataclass(slots=True)
class ConnectionProfile:
    name: str
    profile_type: ProfileType
    protocol: ProtocolType
    host: str
    port: int
    username: str
    auth_type: AuthType
    id: str = field(default_factory=lambda: str(uuid4()))
    password_secret_ref: str | None = None
    ssh_private_key_path: str | None = None
    ssh_private_key_passphrase_secret_ref: str | None = None
    default_local_path: str | None = None
    default_remote_path: str | None = None
    environment_notes: str | None = None
    domain_mapping: str | None = None
    public_url_mapping: str | None = None
    options: dict[str, object] = field(default_factory=dict)
    created_date: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_connected_date: datetime | None = None

    @classmethod
    def quick_sftp(
        cls,
        *,
        host: str,
        port: int,
        username: str,
        auth_type: AuthType,
        name: str | None = None,
        default_remote_path: str | None = None,
        ssh_private_key_path: str | None = None,
    ) -> "ConnectionProfile":
        return cls(
            name=name or f"{username}@{host}",
            profile_type=ProfileType.GENERIC_SSH_SFTP,
            protocol=ProtocolType.SFTP,
            host=host,
            port=port,
            username=username,
            auth_type=auth_type,
            ssh_private_key_path=ssh_private_key_path,
            default_remote_path=default_remote_path or ".",
        )

    @property
    def connection_options(self) -> ConnectionOptions:
        return ConnectionOptions.from_mapping(self.options)
