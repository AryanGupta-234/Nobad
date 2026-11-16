from __future__ import annotations

from pathlib import Path


def test_local_terminal_guards_posix_only_imports() -> None:
    source = Path("terminal/local_pty_terminal.py").read_text(encoding="utf-8")

    assert 'if os.name == "posix":' in source
    assert "import fcntl" in source
    assert "fcntl = None" in source


def test_local_build_runner_uses_windows_safe_process_controls() -> None:
    source = Path("deployment/local_build_runner.py").read_text(encoding="utf-8")

    assert 'start_new_session=os.name == "posix"' in source
    assert "process.terminate()" in source
    assert "process.kill()" in source
