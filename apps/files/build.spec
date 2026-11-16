# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Remote File Manager.
#
# Build with:
#   uv run --with pyinstaller pyinstaller --clean --noconfirm build.spec
#   OR
#   pyinstaller --clean --noconfirm build.spec
#
# Output:
#   dist/RemoteFileManager/RemoteFileManager
#
# Create Debian (.deb) package with:
#   ./packaging/linux/build-deb.sh
#
# Windows output:
#   dist/RemoteFileManager/RemoteFileManager.exe

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


ROOT = Path(globals().get("SPECPATH", ".")).resolve()
APP_NAME = "RemoteFileManager"
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
]

for distribution in [
    "PySide6",
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
]:
    datas += safe_copy_metadata(distribution)

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtNetwork",
    "PySide6.QtPrintSupport",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
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
    "ui",
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
