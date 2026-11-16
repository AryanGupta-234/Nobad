from __future__ import annotations

import re
from pathlib import PurePosixPath

SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sql",
    ".sqlite",
    ".db",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*=\s*([^\s]+)"),
]


def is_sensitive_path(path: str) -> bool:
    name = PurePosixPath(path).name
    lowered = name.lower()
    return lowered in SENSITIVE_NAMES or any(lowered.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
    return redacted

