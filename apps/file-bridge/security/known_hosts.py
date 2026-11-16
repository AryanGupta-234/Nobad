from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.private_paths import app_data_dir, ensure_private_file


@dataclass(frozen=True, slots=True)
class KnownHostRecord:
    host: str
    port: int
    fingerprint_sha256: str
    first_seen: datetime
    last_seen: datetime


class KnownHostStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, int], KnownHostRecord] = {}

    def verify_or_trust(self, host: str, port: int, public_key_bytes: bytes) -> tuple[bool, str | None]:
        fingerprint = fingerprint_sha256(public_key_bytes)
        key = (host, port)
        now = datetime.now(UTC)
        existing = self._records.get(key)
        if existing is None:
            self._records[key] = KnownHostRecord(host, port, fingerprint, now, now)
            return True, "First host fingerprint trusted and cached."
        if existing.fingerprint_sha256 != fingerprint:
            return False, "SSH host fingerprint changed."
        self._records[key] = KnownHostRecord(host, port, fingerprint, existing.first_seen, now)
        return True, None


def fingerprint_sha256(public_key_bytes: bytes) -> str:
    digest = hashlib.sha256(public_key_bytes).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def default_known_hosts_path(home: Path | None = None) -> Path:
    """``~/.remote-file-manager/known_hosts``: folder 0700, file 0600 (#31)."""
    return ensure_private_file(app_data_dir(home) / "known_hosts")


def openssh_known_hosts_path(home: Path | None = None) -> Path:
    root = home or Path.home()
    return root / ".ssh" / "known_hosts"


def known_hosts_files(home: Path | None = None) -> list[str]:
    files: list[str] = []
    openssh_file = openssh_known_hosts_path(home)
    if openssh_file.is_file():
        files.append(str(openssh_file))
    try:
        files.append(str(default_known_hosts_path(home)))
    except OSError:
        # Restricted environments can make the home directory read-only. In
        # that case, keep using OpenSSH known_hosts instead of failing connect.
        pass
    return files


def known_host_pattern(host: str, port: int) -> str:
    clean_host = host.strip().strip("[]")
    return clean_host if port == 22 else f"[{clean_host}]:{port}"


def trust_host_key(host: str, port: int, public_key: str, home: Path | None = None) -> Path:
    """Atomically replace this app's trusted key for a host and port."""
    path = default_known_hosts_path(home)
    pattern = known_host_pattern(host, port)
    key_parts = public_key.strip().split()
    if len(key_parts) < 2:
        raise ValueError("Invalid OpenSSH public key data.")
    normalized_key = " ".join(key_parts[:2])

    retained: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                retained.append(line)
                continue
            fields = stripped.split()
            host_field_index = 1 if fields[0].startswith("@") else 0
            if len(fields) <= host_field_index:
                retained.append(line)
                continue
            patterns = fields[host_field_index].split(",")
            if pattern not in patterns:
                retained.append(line)

    retained.append(f"{pattern} {normalized_key}")
    content = "\n".join(retained).rstrip() + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix="known_hosts-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).chmod(0o600)
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()
    return path
