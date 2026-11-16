from __future__ import annotations

import asyncio

from core.result import OperationResult
from file_ops.archive_models import ArchiveFormat, ArchiveOperationRequest
from file_ops.remote_archive_ops import (
    RemoteArchiveOperations,
    build_remote_tar_create_command,
    build_remote_zip_create_command,
    parse_tar_verbose_listing,
    parse_unzip_listing,
    parse_zipinfo_link_warnings,
    sh_quote,
)


class FakeConnection:
    def __init__(self, responses: dict[str, tuple[int, str, str]]) -> None:
        self.responses = responses
        self.commands: list[str] = []

    async def run_command(self, command: str, *, cwd: str | None = None):
        self.commands.append(command)
        exit_status, stdout, stderr = self.responses.get(command, (0, "", ""))
        return OperationResult.success(
            "Command completed.",
            data={"exit_status": exit_status, "stdout": stdout, "stderr": stderr},
        )


def test_remote_command_builder_quotes_paths() -> None:
    command = build_remote_zip_create_command(["/var/www/my site"], "/tmp/site backup.zip")

    assert command == "cd '/var/www' && zip -r '/tmp/site backup.zip' 'my site'"
    assert sh_quote("a'b") == "'a'\"'\"'b'"


def test_remote_tar_command_builder() -> None:
    command = build_remote_tar_create_command(["/var/www/site"], "/tmp/site.tar.gz")

    assert command == "cd '/var/www' && tar -czf '/tmp/site.tar.gz' 'site'"


def test_parse_unzip_listing() -> None:
    output = """
Archive:  site.zip
  Length      Date    Time    Name
---------  ---------- -----   ----
        5  2026-06-04 13:00   index.html
---------                     -------
        5                     1 file
"""

    members = parse_unzip_listing(output)

    assert members[0].name == "index.html"
    assert members[0].size == 5


def test_parse_tar_listing_detects_links() -> None:
    output = "lrwxrwxrwx user/group 0 2026-06-04 13:00 link -> /etc/passwd\n-rw-r--r-- user/group 5 2026-06-04 13:00 index.html"

    members, warnings = parse_tar_verbose_listing(output)

    assert members[0].is_link
    assert warnings == ["Archive member is a link: link"]
    assert members[1].name == "index.html"


def test_parse_zipinfo_links() -> None:
    output = "lrwxrwxrwx  2.0 unx        11 bx stor 26-Jun-04 13:00 link"

    assert parse_zipinfo_link_warnings(output) == ["Archive member is a link: link"]


def test_remote_missing_command_returns_local_relay_guidance() -> None:
    conn = FakeConnection({"command -v 'zip'": (1, "", "missing")})
    ops = RemoteArchiveOperations(conn)
    request = ArchiveOperationRequest(
        sources=["/var/www/site"],
        destination="/tmp/site.zip",
        archive_format=ArchiveFormat.ZIP,
    )

    result = asyncio.run(ops.create(request))

    assert not result.ok
    assert "Remote command unavailable: zip." == result.message
    assert "local relay" in result.suggested_fix.lower()


def test_remote_preview_zip_parses_members() -> None:
    conn = FakeConnection(
        {
            "command -v 'unzip'": (0, "/usr/bin/unzip\n", ""),
            "unzip -l '/tmp/site.zip'": (
                0,
                "        5  2026-06-04 13:00   index.html\n",
                "",
            ),
            "unzip -Z -l '/tmp/site.zip'": (0, "-rw-r--r--  2.0 unx 5 tx defN 26-Jun-04 13:00 index.html\n", ""),
        }
    )

    result = asyncio.run(RemoteArchiveOperations(conn).preview("/tmp/site.zip", destination="/tmp/extract"))

    assert result.ok
    assert result.data.member_names == ["index.html"]


def test_remote_folder_size_uses_du_fallback() -> None:
    conn = FakeConnection(
        {
            "command -v 'du'": (0, "/usr/bin/du\n", ""),
            "du -sb '/var/www'": (1, "", "unsupported"),
            "du -sk '/var/www'": (0, "4\t/var/www\n", ""),
        }
    )

    result = asyncio.run(RemoteArchiveOperations(conn).calculate_folder_size("/var/www"))

    assert result.ok
    assert result.data.size_bytes == 4096
