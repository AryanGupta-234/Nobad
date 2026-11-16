from __future__ import annotations

from pathlib import Path


def test_main_window_opens_maximized() -> None:
    source = Path("app/main.py").read_text(encoding="utf-8")

    assert "window.showMaximized" in source
    assert "QTimer.singleShot(0, window.showMaximized)" in source
    assert "window.resize(1440, 900)" not in source
