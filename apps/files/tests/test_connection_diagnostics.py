from __future__ import annotations

import errno

from core.connections.ssh_async import classify_connect_error


def test_connection_refused_has_actionable_fix() -> None:
    exc = ConnectionRefusedError(errno.ECONNREFUSED, "Connect call failed")

    result = classify_connect_error("example.com", 22, exc)

    assert not result.ok
    assert "refused" in result.message.lower()
    assert result.suggested_fix is not None
    assert "port is correct" in result.suggested_fix


def test_host_key_error_is_not_retryable() -> None:
    result = classify_connect_error("example.com", 22, RuntimeError("Host key is not trusted"))

    assert not result.ok
    assert not result.retryable
    assert "host key" in result.message.lower()

