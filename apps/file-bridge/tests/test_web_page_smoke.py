"""Every screen of the web UI opens in a real Chromium engine (Qt WebEngine) without a JavaScript error.

On Linux this is the engine the app itself uses when GTK's WebKit isn't installed, so CI (Ubuntu) checks the page
there on every change."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(find_spec("PySide6") is None or find_spec("PySide6.QtWebEngineWidgets") is None,
                    reason="needs Qt WebEngine (PySide6)")
def test_every_screen_opens_without_javascript_errors(tmp_path: Path) -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    run = subprocess.run([sys.executable, str(HERE / "web_page_smoke.py"), str(tmp_path)], capture_output=True, text=True,
                         timeout=150, env=env)
    line = next((x for x in run.stdout.splitlines() if x.startswith("SMOKE ")), None)
    assert line, f"no result\nstdout: {run.stdout[-2000:]}\nstderr: {run.stderr[-3000:]}"
    result = json.loads(line[len("SMOKE "):])
    assert result["loaded"], result
    assert result["errors"] == [], result["errors"]
    for screen, state in result["screens"].items():
        assert state.get("rendered") and state.get("real") and state.get("rail") >= 13, (screen, state)
        assert state.get("text", 0) > 20, (screen, state)
