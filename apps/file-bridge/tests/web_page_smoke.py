"""Load the real web UI in Qt WebEngine (Chromium, the engine File Bridge uses on Linux when GTK's WebKit isn't
installed), open every screen, and report JavaScript errors as JSON. Run by tests/test_web_page_smoke.py in its own
process, because QtWebEngine must be imported before any QApplication exists.

    python tests/web_page_smoke.py <scratch-folder>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

from PySide6.QtWebEngineCore import QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtCore import QCoreApplication, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SCREENS = ["files", "connections", "terminal", "editor", "sync", "deploy", "vault", "dashboard", "services", "tunnels",
           "logs", "playbooks", "settings"]


class Page(QWebEnginePage):
    def __init__(self, errors: list[str]) -> None:
        super().__init__()
        self.errors = errors

    def javaScriptConsoleMessage(self, level, message, line, source):  # type: ignore[no-untyped-def]  # noqa: N802
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.errors.append(f"{Path(source).name}:{line} {message}")


def main(scratch: Path) -> int:
    home = scratch / "home"
    home.mkdir(parents=True, exist_ok=True)
    Path.home = staticmethod(lambda: home)        # never touch the real home or ~/.remote-file-manager
    from app_web.context import AppContext
    from app_web.server import BridgeServer

    ctx = AppContext.create(scratch / "app.sqlite3")
    server = BridgeServer(ctx)
    server.start()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    errors: list[str] = []
    result: dict = {"errors": errors, "screens": {}, "loaded": False}
    view = QWebEngineView()
    page = Page(errors)
    view.setPage(page)
    view.resize(1280, 820)
    queue = list(SCREENS)

    def finish() -> None:
        server.stop()
        print("SMOKE " + json.dumps(result), flush=True)
        app.quit()

    def check(screen: str) -> None:
        js = ("(function(){var s=document.querySelector('.screen[data-screen=\"%s\"]');"
              "return JSON.stringify({rendered:!!s, real:!!(window.NB&&NB.screens&&NB.screens['%s']),"
              "rail:document.querySelectorAll('.rail-item').length, text:s?s.textContent.length:0});})()") % (screen, screen)
        page.runJavaScript(js, 0, lambda value: (result["screens"].__setitem__(screen, json.loads(value or "{}")), step()))

    def step() -> None:
        if not queue:
            finish()
            return
        screen = queue.pop(0)
        page.runJavaScript(f"location.hash = '#/{screen}';", 0)
        QTimer.singleShot(700, lambda: check(screen))

    def loaded(ok: bool) -> None:
        if result["loaded"]:
            return
        result["loaded"] = bool(ok)
        QTimer.singleShot(1500, step)

    page.loadFinished.connect(loaded)
    view.load(QUrl(server.launch_url()))
    QTimer.singleShot(90_000, finish)                 # never hang the test run
    app.exec()
    return 0 if result["loaded"] and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
