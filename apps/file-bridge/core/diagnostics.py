from __future__ import annotations

from datetime import datetime, UTC
import faulthandler
from pathlib import Path
import sys
import tempfile
import traceback

try:
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
except Exception:  # pragma: no cover - PySide import availability
    qInstallMessageHandler = None  # type: ignore[assignment]
    QtMsgType = None  # type: ignore[assignment]


_diagnostic_handle = None
_diagnostic_path: Path | None = None


def diagnostics_dir() -> Path:
    folder = Path.home() / ".remote-file-manager" / "diagnostics"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    except Exception:
        fallback = Path(tempfile.gettempdir()) / "remote-file-manager" / "diagnostics"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def install_diagnostics() -> Path:
    global _diagnostic_handle, _diagnostic_path
    try:
        folder = diagnostics_dir()
        _diagnostic_path = folder / "latest.log"
        _diagnostic_handle = _diagnostic_path.open("a", encoding="utf-8", buffering=1)
        log_diagnostic("diagnostics", "Diagnostics initialized.")
        try:
            faulthandler.enable(file=_diagnostic_handle)
        except Exception:
            pass
    except Exception:
        pass

    previous_hook = sys.excepthook

    def excepthook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        log_diagnostic("uncaught_exception", details)
        previous_hook(exc_type, exc, tb)

    sys.excepthook = excepthook

    if qInstallMessageHandler is not None:
        qInstallMessageHandler(_qt_message_handler)
    return _diagnostic_path


def log_diagnostic(operation: str, message: str) -> None:
    global _diagnostic_handle
    line = f"{datetime.now(UTC).isoformat()} [{operation}] {message}\n"
    if _diagnostic_handle is not None:
        try:
            _diagnostic_handle.write(line)
            return
        except Exception:
            pass
    try:
        folder = diagnostics_dir()
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "latest.log").open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def _qt_message_handler(mode, context, message: str) -> None:  # type: ignore[no-untyped-def]
    category = getattr(context, "category", "") or "qt"
    log_diagnostic(f"qt:{mode}", f"{category}: {message}")
    if QtMsgType is not None and mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        sys.stderr.write(f"[{category}] {message}\n")
