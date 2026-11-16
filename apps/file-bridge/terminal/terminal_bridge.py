from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TerminalBridgeState:
    connected: bool = False
    cwd: str | None = None
    last_error: str | None = None


def normalize_terminal_paste(text: str) -> str:
    """Convert clipboard newlines into terminal Enter keystrokes.

    Many GUI clipboards expose pasted line breaks as LF. In a raw terminal app,
    LF is Ctrl+J, which nano treats as "Justify paragraph". Terminals send CR
    for Enter, so normalize pasted line endings before writing to the PTY.
    """

    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r")
