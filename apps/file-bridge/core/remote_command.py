"""Reading the result of ``connection.run_command``.

``run_command`` reports *that the command ran* (``result.ok``); whether it worked is its exit status. Callers that
only look at ``result.ok`` report "done" for a ``systemctl restart`` that failed. These helpers check both.

``sudo -n`` (non-interactive) makes sudo fail at once with "a password is required" instead of waiting for a
password on a command channel nobody types into. The app never types a password into a server's prompt here."""
from __future__ import annotations

from typing import Any

SUDO = "sudo -n "
PASSWORD_HINTS = ("a password is required", "a terminal is required", "no tty present", "askpass")


def exit_status(result: Any) -> int | None:
    data = getattr(result, "data", None)
    if isinstance(data, dict) and data.get("exit_status") is not None:
        try:
            return int(data["exit_status"])
        except (TypeError, ValueError):
            return None
    return None


def command_ok(result: Any) -> bool:
    """The command ran and exited with 0 (a result without an exit status counts as 0)."""
    return bool(getattr(result, "ok", False)) and exit_status(result) in (None, 0)


def stderr_of(result: Any) -> str:
    data = getattr(result, "data", None)
    return str(data.get("stderr") or "") if isinstance(data, dict) else ""


def sudo_needs_password(result: Any) -> bool:
    text = stderr_of(result).lower()
    return any(hint in text for hint in PASSWORD_HINTS)


def command_error(result: Any, what: str) -> str:
    """A short, plain reason for a failed command: sudo's password case, else the last lines of stderr."""
    if sudo_needs_password(result):
        return (f"{what}: sudo on this server asks for a password. Allow passwordless sudo for this command, "
                "or connect as a user who may run it.")
    err = " ".join(line.strip() for line in stderr_of(result).strip().splitlines()[-3:] if line.strip())
    if err:
        return f"{what}: {err[:300]}"
    status = exit_status(result)
    if not getattr(result, "ok", False):
        return f"{what}: {getattr(result, 'message', 'the command could not run')}"
    return f"{what}: the command exited with status {status}."


def sudo_prefix(sudo: bool) -> str:
    return SUDO if sudo else ""
