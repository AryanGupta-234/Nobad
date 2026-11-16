from __future__ import annotations

from core.connections.capabilities import ConnectionCapabilities


def test_sftp_without_shell_disables_terminal() -> None:
    caps = ConnectionCapabilities.sftp(has_shell=False)
    assert caps.can_list
    assert caps.can_edit
    assert not caps.can_terminal
    assert not caps.can_remote_zip


def test_sftp_with_shell_enables_terminal_and_remote_commands() -> None:
    caps = ConnectionCapabilities.sftp(has_shell=True)
    assert caps.can_terminal
    assert caps.can_exec_command
    assert caps.can_remote_zip


def test_rclone_does_not_claim_chmod_or_terminal() -> None:
    caps = ConnectionCapabilities.rclone()
    assert caps.can_rclone
    assert caps.can_copy
    assert not caps.can_chmod
    assert not caps.can_terminal

