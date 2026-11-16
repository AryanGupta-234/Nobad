"""Screenshots of the web UI with headless Microsoft Edge, for design review (never commit the images).

Runs the real web UI server on a temporary database (your real data is never touched), then captures each screen
in dark and light at the normal and the minimum window size.

    python -I scripts/ui_screenshots.py <output folder> [screen ...] [--fx]   (--fx: Visual effects on)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from app_web import bus  # noqa: E402
from app_web.context import AppContext  # noqa: E402
from app_web.server import BridgeServer  # noqa: E402

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "microsoft-edge", "msedge", "chromium", "google-chrome",
]
SIZES = {"1280x820": (1280, 820), "1060x700": (1060, 700)}
DEFAULT_SCREENS = ["files", "settings", "connections"]


class PreviewWindow:
    """Stands in for the frameless pywebview window, so screenshots show the NOBAD title bar."""

    def state(self) -> dict:
        return {"frameless": True, "maximized": False}

    def action(self, act: str, edge: str | None = None) -> dict:
        return self.state()


def find_browser() -> str:
    for candidate in EDGE_CANDIDATES:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise SystemExit("Microsoft Edge (or Chromium) wasn't found.")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    out = Path(argv[0]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    screens = [a for a in argv[1:] if not a.startswith("--")] or DEFAULT_SCREENS
    browser = find_browser()
    work = Path(tempfile.mkdtemp(prefix="nbfb-shots-"))
    ctx = AppContext.create(work / "app.sqlite3")
    ctx.window = PreviewWindow()      # shows NOBAD's title bar as in the frameless app window
    server = BridgeServer(ctx)
    server.start()
    bus.log("NOBAD File Bridge 0.4.0 started.", "ok")
    bus.log("Preview data: a temporary database, nothing real.", "info")
    try:
        fx = "--fx" in argv
        ctx.settings.set("web_ui.visual_effects", fx)
        for theme in ("dark", "light"):
            ctx.settings.set("web_ui.theme", theme)
            for screen in screens:
                for size_name, (width, height) in SIZES.items():
                    target = out / f"{screen}-{theme}-{size_name}{'-fx' if fx else ''}.png"
                    profile = work / f"profile-{theme}-{screen}-{size_name}"
                    subprocess.run(
                        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                         f"--user-data-dir={profile}", f"--window-size={width},{height}",
                         "--timeout=3500", "--force-prefers-reduced-motion", f"--screenshot={target}",
                         f"{server.launch_url()}#/{screen}"],
                        check=False, capture_output=True, timeout=90,
                    )
                    print(("ok   " if target.exists() else "FAIL ") + str(target))
    finally:
        server.stop()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
