"""The app's entry point opens the web UI, and the package ships it (the classic Qt window is gone)."""
from __future__ import annotations

import sys
import tomllib
import types
from pathlib import Path

import pytest

from app import main as entry


def test_the_app_starts_the_web_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setitem(sys.modules, "app.web", types.SimpleNamespace(main=lambda argv: seen.append(argv) or 0))
    assert entry.main(["--browser"]) == 0
    assert seen == [["--browser"]]


def test_classic_explains_that_it_was_removed(capsys: pytest.CaptureFixture[str]) -> None:
    assert entry.main(["--classic"]) == 2
    assert "removed" in capsys.readouterr().err


def test_no_qt_ui_is_left() -> None:
    assert not Path("ui").exists() and not Path("app/classic.py").exists()
    for path in Path(".").rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "from ui." not in text and "import ui." not in text, path


def test_the_package_ships_the_web_ui_files() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    setup = project["tool"]["setuptools"]
    assert {"app_web", "app_web.handlers"} <= set(setup["packages"]) and "ui" not in setup["packages"]
    assert "ui/screens/*.js" in setup["package-data"]["app_web"]
    assert project["project"]["scripts"]["nobad-file-bridge"] == "app.main:main"
    pyside = [d for d in project["project"]["dependencies"] if d.startswith("PySide6")]
    assert pyside and all("sys_platform == 'linux'" in d for d in pyside)        # only the Linux window needs Qt
    spec = Path("build.spec").read_text(encoding="utf-8")
    assert '"app_web/ui"' in spec and 'collect_data_files("webview")' in spec and '"ui",' not in spec
