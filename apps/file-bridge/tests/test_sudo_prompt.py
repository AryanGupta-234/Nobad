"""The sudo password is only typed into sudo's own random prompt, once (issue #32)."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

import pytest

from core.playbooks_manager import (
    PASSWORD_MASK,
    SUDO_ASKED_AGAIN_NOTICE,
    SUDO_PROMPT_SHOWN,
    PlaybookStreamingRunner,
    SudoPromptResponder,
    choose_sudo_password,
    script_uses_sudo,
)

PASSWORD = "hunter2-secret"
NONCE = re.compile(r"nobad-sudo-[0-9a-f]{32}")


class FakeStdin:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, data: str) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None


class FakeStdout:
    def __init__(self, process: "FakeProcess") -> None:
        self.process = process

    async def read(self, size: int) -> str:
        return self.process.next_chunk()


class FakeProcess:
    """Plays back output chunks; ``script(prompt)`` builds them once the runner's command (and nonce) is known."""

    def __init__(self, script: Callable[[str], list[str]]) -> None:
        self.script = script
        self.command = ""
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(self)
        self.exit_status = 0
        self._chunks: list[str] | None = None

    def next_chunk(self) -> str:
        if self._chunks is None:
            found = NONCE.search(self.command)
            self._chunks = self.script(found.group(0) if found else "<no nonce>")
        return self._chunks.pop(0) if self._chunks else ""

    async def wait(self) -> None:
        return None

    def terminate(self) -> None:
        return None


class FakeRawConnection:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process

    async def create_process(self, command: str, **kwargs):
        self.process.command = command
        return self.process


class FakeConnection:
    def __init__(self, process: FakeProcess) -> None:
        self.raw_connection = FakeRawConnection(process)


def _run(script: Callable[[str], list[str]], *, sudo_password: str | None = PASSWORD, body: str = "sudo whoami"):
    process = FakeProcess(script)
    shown: list[str] = []
    result = asyncio.run(PlaybookStreamingRunner(FakeConnection(process)).run(body, shown.append, sudo_password=sudo_password))
    return process, "".join(shown), result


def _password_writes(process: FakeProcess) -> list[str]:
    return [w for w in process.stdin.writes if PASSWORD in w]


def test_output_that_only_looks_like_a_sudo_prompt_never_gets_the_password() -> None:
    process, shown, _ = _run(lambda prompt: [
        "tail of a log file:\n",
        "[sudo] password for deploy: \n",       # printed by a log line / hostile program, not by sudo
        "Password: ",
        "done\n",
    ])

    assert _password_writes(process) == []
    assert "[sudo] password for deploy" in shown


def test_sudos_own_random_prompt_is_answered_once() -> None:
    process, shown, result = _run(lambda prompt: [f"{prompt}", "root\n"])

    assert re.search(r"export SUDO_PROMPT=nobad-sudo-[0-9a-f]{32}\n", process.command)
    assert _password_writes(process) == [f"{PASSWORD}\n"]
    assert SUDO_PROMPT_SHOWN in shown
    assert not NONCE.search(shown), "the random prompt is replaced before it is shown"
    assert result.ok


def test_a_prompt_split_across_chunks_is_still_recognised() -> None:
    process, shown, _ = _run(lambda prompt: ["working\n" + prompt[:10], prompt[10:25], prompt[25:], "root\n"])

    assert _password_writes(process) == [f"{PASSWORD}\n"]
    assert shown == f"working\n{SUDO_PROMPT_SHOWN}root\n"


def test_a_second_prompt_is_not_answered_again() -> None:
    process, shown, _ = _run(lambda prompt: [prompt, "Sorry, try again.\n", prompt, ""])

    assert len(_password_writes(process)) == 1
    assert SUDO_ASKED_AGAIN_NOTICE in shown


def test_an_echoed_password_is_masked_in_the_output_and_the_saved_result() -> None:
    process, shown, result = _run(lambda prompt: [prompt, PASSWORD[:6], PASSWORD[6:] + "\n", "root\n"])

    assert PASSWORD not in shown
    assert PASSWORD_MASK in shown
    assert PASSWORD not in result.data["output"]


def test_without_a_sudo_password_nothing_is_sent_and_the_script_is_unchanged() -> None:
    process, shown, _ = _run(lambda prompt: ["[sudo] password for deploy: "], sudo_password=None)

    assert process.stdin.writes == []
    assert "SUDO_PROMPT" not in process.command


def test_each_run_gets_a_new_prompt() -> None:
    assert SudoPromptResponder(PASSWORD).prompt != SudoPromptResponder(PASSWORD).prompt


# ---------------------------------------------------------------- reuse of the SSH login password is opt-in
def test_login_password_is_not_reused_by_default() -> None:
    assert choose_sudo_password(typed_password="", reuse_login_password=False, login_password="ssh-pass") is None


def test_login_password_is_reused_only_when_opted_in() -> None:
    assert choose_sudo_password(typed_password="", reuse_login_password=True, login_password="ssh-pass") == "ssh-pass"


def test_a_typed_sudo_password_wins() -> None:
    assert choose_sudo_password(typed_password="sudo-pass", reuse_login_password=True, login_password="ssh") == "sudo-pass"


@pytest.mark.parametrize(("script", "expected"), [
    ("sudo systemctl reload nginx", True),
    ("if true; then\n  sudo apt-get clean\nfi", True),
    ("echo pseudo-terminal", False),
    ("ls -la /var/www", False),
])
def test_script_uses_sudo(script: str, expected: bool) -> None:
    assert script_uses_sudo(script) is expected
