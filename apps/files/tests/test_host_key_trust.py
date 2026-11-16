from __future__ import annotations

from pathlib import Path

import pytest

import core.connections.ssh_async as ssh_async
from core.connections.profile import AuthType, ConnectionProfile
from core.connections.ssh_async import HostKeyPrompt, SSHConnection
from security.known_hosts import trust_host_key


class _FakeHostKey:
    def __init__(self, fingerprint: str, public_key: str) -> None:
        self.fingerprint = fingerprint
        self.public_key = public_key

    def get_algorithm(self) -> str:
        return "ssh-ed25519"

    def get_fingerprint(self, _hash_name: str = "sha256") -> str:
        return self.fingerprint

    def export_public_key(self, _format_name: str = "openssh") -> bytes:
        return self.public_key.encode("ascii")


def _profile() -> ConnectionProfile:
    return ConnectionProfile.quick_sftp(
        name="New server",
        host="new.example.com",
        port=22,
        username="deploy",
        auth_type=AuthType.PASSWORD,
    )


@pytest.mark.asyncio
async def test_unknown_ssh_host_returns_fingerprint_prompt(monkeypatch) -> None:
    presented = _FakeHostKey("SHA256:new-key", "ssh-ed25519 AAAANEW")
    monkeypatch.setattr(ssh_async, "_known_hosts_lookup", lambda *_args: ((), (), (), (), (), (), ()))

    async def reject_unknown(_host: str, **kwargs):
        verifier = kwargs["client_factory"]()
        verifier.validate_host_public_key("new.example.com", "203.0.113.10", 22, presented)
        raise RuntimeError("Host key is not trusted")

    monkeypatch.setattr(ssh_async.asyncssh, "connect", reject_unknown)

    result = await SSHConnection(_profile()).connect(password="not-logged")

    assert not result.ok
    assert isinstance(result.data, HostKeyPrompt)
    assert result.data.fingerprint == "SHA256:new-key"
    assert not result.data.changed
    assert "authenticity" in result.message.lower()


@pytest.mark.asyncio
async def test_changed_ssh_host_returns_strong_warning(monkeypatch) -> None:
    previous = _FakeHostKey("SHA256:old-key", "ssh-ed25519 AAAAOLD")
    presented = _FakeHostKey("SHA256:new-key", "ssh-ed25519 AAAANEW")
    monkeypatch.setattr(
        ssh_async,
        "_known_hosts_lookup",
        lambda *_args: ((previous,), (), (), (), (), (), ()),
    )

    async def reject_changed(_host: str, **kwargs):
        verifier = kwargs["client_factory"]()
        verifier.validate_host_public_key("new.example.com", "203.0.113.10", 22, presented)
        raise RuntimeError("Host key is not trusted")

    monkeypatch.setattr(ssh_async.asyncssh, "connect", reject_changed)

    result = await SSHConnection(_profile()).connect(password="not-logged")

    assert not result.ok
    assert result.data.changed
    assert result.data.previous_fingerprints == ("SHA256:old-key",)
    assert "changed" in result.message.lower()


def test_trusting_host_key_replaces_app_entry_atomically(tmp_path: Path) -> None:
    path = trust_host_key(
        "example.com",
        65002,
        "ssh-ed25519 AAAAOLD",
        home=tmp_path,
    )
    trust_host_key(
        "example.com",
        65002,
        "ssh-ed25519 AAAANEW",
        home=tmp_path,
    )

    content = path.read_text(encoding="utf-8")
    assert content == "[example.com]:65002 ssh-ed25519 AAAANEW\n"
    assert path.stat().st_mode & 0o777 == 0o600
