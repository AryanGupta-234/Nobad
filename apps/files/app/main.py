from __future__ import annotations

import os
import sys

# Force Qt to use the generic platform theme to avoid GLib-GIO abort with GNOME xsettings on Linux
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "generic")
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")

from PySide6.QtCore import QCoreApplication, QTimer, Qt
from PySide6.QtWidgets import QApplication
# Import QtWebEngineWidgets early so Chromium hooks into the application loop before GUI init
from PySide6.QtWebEngineWidgets import QWebEngineView

from core.diagnostics import install_diagnostics
from ui.branding import application_icon
from ui.main_window import MainWindow
from ui.workbench_models import create_dark_palette


def main() -> int:
    install_diagnostics()
    # Ensure OpenGL contexts are shared across Qt and QtWebEngine before QApplication construction.
    # On Linux (Wayland / X11), QtWebEngine requires this to avoid destroying and recreating the top-level
    # native window when a WebEngineView is instantiated.
    if sys.platform.startswith("linux"):
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setPalette(create_dark_palette())
    app.setApplicationName("Remote File Manager")
    app.setApplicationDisplayName("Remote File Manager")
    app.setOrganizationName("Remote File Manager")
    app.setDesktopFileName("remote-file-manager")
    icon = application_icon()
    app.setWindowIcon(icon)

    window = MainWindow()
    window.setWindowIcon(icon)
    # Map first, then maximize. This is more reliable with GNOME/X11 and
    # Wayland window managers than requesting maximization before mapping.
    window.show()
    QTimer.singleShot(0, window.showMaximized)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
