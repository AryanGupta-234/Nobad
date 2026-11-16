from __future__ import annotations

from pathlib import Path

import security.known_hosts as known_hosts


def test_known_hosts_files_tolerates_app_file_create_failure(monkeypatch, tmp_path: Path) -> None:
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    openssh_file = ssh_dir / "known_hosts"
    openssh_file.write_text("example.com ssh-ed25519 AAAA\n", encoding="utf-8")

    def fail_default_path(home: Path | None = None) -> Path:
        raise OSError("read-only")

    monkeypatch.setattr(known_hosts, "default_known_hosts_path", fail_default_path)

    assert known_hosts.known_hosts_files(tmp_path) == [str(openssh_file)]
