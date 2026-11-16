from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnectionCapabilities:
    can_list: bool = False
    can_upload: bool = False
    can_download: bool = False
    can_rename: bool = False
    can_move: bool = False
    can_copy: bool = False
    can_delete: bool = False
    can_chmod: bool = False
    can_edit: bool = False
    can_terminal: bool = False
    can_exec_command: bool = False
    can_remote_zip: bool = False
    can_remote_unzip: bool = False
    can_calculate_size: bool = False
    can_checksum: bool = False
    can_symlink: bool = False
    can_preserve_permissions: bool = False
    can_server_to_server_transfer: bool = False
    can_rsync: bool = False
    can_rclone: bool = False
    can_public_url_mapping: bool = False

    def allows(self, capability_name: str) -> bool:
        if not hasattr(self, capability_name):
            raise AttributeError(f"Unknown capability: {capability_name}")
        return bool(getattr(self, capability_name))

    @classmethod
    def local_filesystem(cls) -> "ConnectionCapabilities":
        return cls(
            can_list=True,
            can_upload=True,
            can_download=True,
            can_rename=True,
            can_move=True,
            can_copy=True,
            can_delete=True,
            can_edit=True,
            can_remote_zip=True,
            can_remote_unzip=True,
            can_calculate_size=True,
            can_checksum=True,
            can_symlink=True,
            can_preserve_permissions=True,
        )

    @classmethod
    def sftp(cls, *, has_shell: bool) -> "ConnectionCapabilities":
        return cls(
            can_list=True,
            can_upload=True,
            can_download=True,
            can_rename=True,
            can_move=True,
            can_copy=True,
            can_delete=True,
            can_chmod=has_shell,
            can_edit=True,
            can_terminal=has_shell,
            can_exec_command=has_shell,
            can_remote_zip=has_shell,
            can_remote_unzip=has_shell,
            can_calculate_size=has_shell,
            can_checksum=has_shell,
            can_symlink=has_shell,
            can_preserve_permissions=True,
            can_server_to_server_transfer=has_shell,
        )

    @classmethod
    def ftp(cls, *, secure: bool) -> "ConnectionCapabilities":
        return cls(
            can_list=True,
            can_upload=True,
            can_download=True,
            can_rename=True,
            can_move=True,
            can_delete=True,
            can_edit=True,
        )

    @classmethod
    def rclone(cls) -> "ConnectionCapabilities":
        return cls(
            can_list=True,
            can_upload=True,
            can_download=True,
            can_rename=True,
            can_move=True,
            can_copy=True,
            can_delete=True,
            can_rclone=True,
        )

    @classmethod
    def unsupported(cls) -> "ConnectionCapabilities":
        return cls()
