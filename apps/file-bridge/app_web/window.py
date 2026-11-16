"""The pywebview window that shows the web UI.

Windows uses Microsoft Edge WebView2 (built into Windows 11 and almost every Windows 10). pywebview can silently
fall back to the old Internet Explorer engine, which can't run this UI safely, so on Windows the Edge engine is
required and a clear message is shown instead. Linux uses GTK WebKit2 when available, else Qt WebEngine."""
from __future__ import annotations

import sys
from typing import Any

WINDOW_TITLE = "NOBAD File Bridge"
WINDOW_SIZE = (1280, 820)
MIN_SIZE = (1060, 700)
BACKGROUND = "#08090d"

WEBVIEW2_MISSING = (
    "NOBAD File Bridge needs Microsoft Edge WebView2 to show its window. Install the WebView2 Runtime from "
    "https://developer.microsoft.com/microsoft-edge/webview2/ and start the app again, or run it with --browser "
    "to use your web browser instead."
)


class WindowUnavailable(RuntimeError):
    pass


def _gui_for_platform() -> str | None:
    if sys.platform == "win32":
        return "edgechromium"
    if sys.platform.startswith("linux"):
        return None            # pywebview picks GTK, then Qt
    return None                # macOS: Cocoa WebKit


def run_window(launch_url: str, *, debug: bool = False) -> None:
    """Open the window and block until it is closed."""
    try:
        import webview
    except ImportError as exc:
        raise WindowUnavailable("pywebview isn't installed. Run the app with --browser, or install pywebview.") from exc

    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    kwargs: dict[str, Any] = dict(
        width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=MIN_SIZE, background_color=BACKGROUND,
        text_select=True,
    )
    webview.create_window(WINDOW_TITLE, launch_url, **kwargs)
    gui = _gui_for_platform()
    try:
        webview.start(gui=gui, debug=debug, private_mode=True)
    except Exception as exc:
        if sys.platform == "win32":
            raise WindowUnavailable(WEBVIEW2_MISSING) from exc
        raise WindowUnavailable(f"Couldn't open the window: {exc}") from exc
