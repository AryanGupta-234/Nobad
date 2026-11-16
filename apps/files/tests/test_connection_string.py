from __future__ import annotations

from core.connections.connection_string import parse_connection_target


def test_parse_plain_ssh_command() -> None:
    parsed = parse_connection_target("ssh nathaniel@160.153.188.182")

    assert parsed is not None
    assert parsed.protocol == "ssh"
    assert parsed.username == "nathaniel"
    assert parsed.host == "160.153.188.182"
    assert parsed.port is None


def test_parse_ssh_command_with_port() -> None:
    parsed = parse_connection_target("ssh -p 2222 nathaniel@example.com")

    assert parsed is not None
    assert parsed.host == "example.com"
    assert parsed.port == 2222


def test_parse_sftp_url() -> None:
    parsed = parse_connection_target("sftp://nathaniel@example.com:2222")

    assert parsed is not None
    assert parsed.protocol == "sftp"
    assert parsed.username == "nathaniel"
    assert parsed.host == "example.com"
    assert parsed.port == 2222
