# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for NOBAD File Bridge.
#
# Build with:
#   uv run --with pyinstaller pyinstaller --clean --noconfirm build.spec
#   OR
#   pyinstaller --clean --noconfirm build.spec
#
# Output:
#   dist/NobadFileBridge/NobadFileBridge
#
# Create Debian (.deb) package with:
#   ./packaging/linux/build-deb.sh
#
# Windows output:
#   dist/NobadFileBridge/NobadFileBridge.exe

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


ROOT = Path(globals().get("SPECPATH", ".")).resolve()
APP_NAME = "NobadFileBridge"
RESOURCES_DIR = ROOT / "resources"
APP_ICON = RESOURCES_DIR / "branding" / "remote-file-manager.ico"


def safe_collect_submodules(package: str) -> list[str]:
    try:
        return collect_submodules(package)
    except Exception:
        return []


def safe_copy_metadata(distribution: str) -> list[tuple[str, str]]:
    try:
        return copy_metadata(distribution)
    except Exception:
        return []


datas = [
    (str(RESOURCES_DIR), "resources"),
    # The app window: pages, styles, scripts and vendored xterm (served by app_web.server from this folder).
    (str(ROOT / "app_web" / "ui"), "app_web/ui"),
]
# pywebview's own files (WebView2 loader and helpers on Windows, JS bridge everywhere).
datas += collect_data_files("webview")

# pywebview backends per platform: Edge WebView2 (WinForms) on Windows; Qt WebEngine through the bundled PySide6 on
# Linux (a frozen app can't import the system's GTK bindings). The others would only make the bundle bigger.
QT_HIDDEN = ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtWebEngineCore",
             "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel", "PySide6.QtNetwork", "PySide6.QtPrintSupport"]
if sys.platform == "win32":
    WEBVIEW_SKIP = (".gtk", ".qt", ".cocoa", ".android", ".cef", ".mshtml")
    PLATFORM_HIDDEN = ["clr", "clr_loader", "pythonnet"]
    PLATFORM_EXCLUDES = ["PySide6", "shiboken6", "qtpy"]       # Windows draws the window with WebView2: no Qt at all
else:
    WEBVIEW_SKIP = (".winforms", ".edgechromium", ".win32", ".mshtml", ".cef", ".cocoa", ".android", ".gtk")
    PLATFORM_HIDDEN = QT_HIDDEN + ["qtpy", "qtpy.QtCore", "qtpy.QtGui", "qtpy.QtWidgets", "qtpy.QtWebEngineWidgets",
                                   "qtpy.QtWebEngineCore", "qtpy.QtWebChannel", "qtpy.QtNetwork"]
    PLATFORM_EXCLUDES = []

for distribution in [
    *([] if sys.platform == "win32" else ["PySide6"]),
    "asyncssh",
    "aioftp",
    "keyring",
    "SQLAlchemy",
    "chardet",
    "Pillow",
    "argon2-cffi",
    "cryptography",
    "secretstorage",
    "jeepney",
    "pywinpty",
    "pywebview",
    "pythonnet",
    "clr_loader",
    "qtpy",
]:
    datas += safe_copy_metadata(distribution)

hiddenimports = [
    *PLATFORM_HIDDEN,
    "winpty",
    "sqlalchemy.dialects.sqlite",
    "cryptography.hazmat.backends.openssl",
    "keyring.backends.SecretService",
    "keyring.backends.chainer",
    "secretstorage",
    "jeepney",
    "jeepney.io.threading",
]

for package in [
    "app",
    "app_web",
    "app_web.handlers",
    "core",
    "core.connections",
    "credentials",
    "deployment",
    "editor",
    "file_ops",
    "security",
    "storage",
    "sync",
    "terminal",
    "transfers",
    "asyncssh",
    "aioftp",
    "keyring",
    "keyring.backends",
    "secretstorage",
    "jeepney",
    "argon2",
    "cryptography",
    "PIL",
    "sqlalchemy",
]:
    hiddenimports += safe_collect_submodules(package)

hiddenimports += [m for m in safe_collect_submodules("webview") if not any(x in m for x in WEBVIEW_SKIP)]
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    ["app/main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "PyQt5",
        "PyQt6",
        "PySide2",
        *PLATFORM_EXCLUDES,
        *(f"webview.platforms{x}" for x in WEBVIEW_SKIP),
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP_ICON) if APP_ICON.exists() else None,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
