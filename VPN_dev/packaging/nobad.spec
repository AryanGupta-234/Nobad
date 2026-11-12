# PyInstaller spec - onedir build (an installer wraps it). Run from the project root:  pyinstaller packaging/nobad.spec
# Deliberately NOT built with uac_admin: a requireAdministrator manifest would force a UAC prompt before NOBAD VPN can
# use its elevated scheduled task. NOBAD VPN elevates itself (or hands over to the task) at startup instead.
import os

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 (provided by PyInstaller)
ROOT = os.path.dirname(HERE)
ICON = os.path.join(ROOT, "nobadvpn", "ui", "brand", "nobad.ico")
VERSION = os.path.join(HERE, "version_info.txt")

# Windows only needs pywebview's WinForms + Edge WebView2 backend; the other backends (and the GUI toolkits they
# would drag in if installed on the build machine) are excluded to keep the app small and quick to start.
hidden = [m for m in collect_submodules("webview")
          if not any(x in m for x in (".gtk", ".qt", ".cocoa", ".android", ".cef", ".mshtml"))] + ["pystray._win32"]
EXCLUDES = ["tkinter", "pytest", "numpy", "PyQt5", "PyQt6", "PySide2", "PySide6",
            "gi", "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cocoa",
            "webview.platforms.android", "webview.platforms.cef"]
a = Analysis([os.path.join(ROOT, "nobad_vpn.py")], pathex=[ROOT],
             datas=[(os.path.join(ROOT, "nobadvpn", "ui"), "nobadvpn/ui")],
             hiddenimports=hidden, excludes=EXCLUDES, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NobadVPN", console=False, disable_windowed_traceback=False,
          icon=ICON, version=VERSION if os.path.exists(VERSION) else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NobadVPN")
