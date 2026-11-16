from __future__ import annotations

from pathlib import Path

from security.known_hosts import default_known_hosts_path, known_hosts_files, openssh_known_hosts_path


def test_known_hosts_files_include_openssh_file_when_present(tmp_path: Path) -> None:
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    openssh_file = ssh_dir / "known_hosts"
    openssh_file.write_text("example.com ssh-ed25519 AAAA\n", encoding="utf-8")

    files = known_hosts_files(tmp_path)

    assert files[0] == str(openssh_known_hosts_path(tmp_path))
    assert files[1] == str(default_known_hosts_path(tmp_path))


def test_known_hosts_files_create_app_file(tmp_path: Path) -> None:
    files = known_hosts_files(tmp_path)

    assert files == [str(default_known_hosts_path(tmp_path))]
    assert Path(files[0]).exists()
