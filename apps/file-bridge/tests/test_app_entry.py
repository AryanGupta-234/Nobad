"""The app's entry point opens the web UI; --classic still reaches the previous Qt window while it ships."""
from __future__ import annotations

import sys
import types

import pytest

from app import main as entry


def test_the_app_starts_the_web_ui_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}
    monkeypatch.setitem(sys.modules, "app.web", types.SimpleNamespace(main=lambda argv: seen.setdefault("web", argv) and 0))
    monkeypatch.setitem(sys.modules, "app.classic", types.SimpleNamespace(main=lambda argv: seen.setdefault("classic", argv) and 0))
    entry.main(["--browser"])
    assert seen == {"web": ["--browser"]}


def test_classic_is_still_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}
    monkeypatch.setitem(sys.modules, "app.web", types.SimpleNamespace(main=lambda argv: seen.setdefault("web", argv) and 0))
    monkeypatch.setitem(sys.modules, "app.classic", types.SimpleNamespace(main=lambda argv: seen.setdefault("classic", argv) and 0))
    entry.main(["--classic", "--x"])
    assert seen == {"classic": ["--x"]}


def test_the_package_ships_the_web_ui_files() -> None:
    import tomllib
    from pathlib import Path

    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    setup = project["tool"]["setuptools"]
    assert {"app_web", "app_web.handlers"} <= set(setup["packages"])
    assert "ui/screens/*.js" in setup["package-data"]["app_web"]
    assert project["project"]["scripts"]["nobad-file-bridge"] == "app.main:main"
    spec = Path("build.spec").read_text(encoding="utf-8")
    assert '"app_web/ui"' in spec and 'collect_data_files("webview")' in spec
