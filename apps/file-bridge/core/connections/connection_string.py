from __future__ import annotations

import shlex
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ConnectionTarget:
    protocol: str | None = None
    username: str | None = None
    host: str | None = None
    port: int | None = None


def parse_connection_target(value: str) -> ConnectionTarget | None:
    text = value.strip()
    if not text:
        return None

    if text.startswith(("ssh://", "sftp://")):
        return _parse_url(text)

    if text.startswith("ssh "):
        return _parse_ssh_command(text)

    if "@" in text and " " not in text:
        return _parse_user_host(text)

    return None


def _parse_url(text: str) -> ConnectionTarget | None:
    parsed = urlparse(text)
    if not parsed.hostname:
        return None
    return ConnectionTarget(
        protocol=parsed.scheme,
        username=parsed.username,
        host=parsed.hostname,
        port=parsed.port,
    )


def _parse_ssh_command(text: str) -> ConnectionTarget | None:
    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    if not parts or parts[0] != "ssh":
        return None

    port: int | None = None
    target: str | None = None
    index = 1
    while index < len(parts):
        part = parts[index]
        if part == "-p" and index + 1 < len(parts):
            port = _parse_port(parts[index + 1])
            index += 2
            continue
        if part.startswith("-p") and len(part) > 2:
            port = _parse_port(part[2:])
            index += 1
            continue
        if not part.startswith("-"):
            target = part
        index += 1

    if not target:
        return None
    parsed = _parse_user_host(target)
    if parsed is None:
        return None
    return ConnectionTarget(protocol="ssh", username=parsed.username, host=parsed.host, port=port or parsed.port)


def _parse_user_host(text: str) -> ConnectionTarget | None:
    username, host_port = text.rsplit("@", 1)
    if not username or not host_port:
        return None

    host = host_port
    port: int | None = None
    if host_port.count(":") == 1:
        maybe_host, maybe_port = host_port.rsplit(":", 1)
        parsed_port = _parse_port(maybe_port)
        if parsed_port is not None:
            host = maybe_host
            port = parsed_port

    return ConnectionTarget(username=username, host=host, port=port)


def _parse_port(value: str) -> int | None:
    try:
        port = int(value)
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None
