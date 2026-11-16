from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


BRANDING_DIR = Path(__file__).resolve().parent.parent / "resources" / "branding"
APP_ICON_PATH = BRANDING_DIR / "remote-file-manager-icon.png"


def application_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        path = BRANDING_DIR / f"remote-file-manager-{size}.png"
        if path.is_file():
            icon.addFile(str(path))
    if icon.isNull() and APP_ICON_PATH.is_file():
        icon.addFile(str(APP_ICON_PATH))
    return icon
