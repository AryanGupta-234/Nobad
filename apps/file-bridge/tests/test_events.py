"""The transfer backend is Qt-free (so the web UI can use it), and the Qt UI still gets its signals on the GUI thread."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from core.events import Event

APP_ROOT = Path(__file__).resolve().parents[1]


def test_event_calls_handlers_in_order_and_disconnect_stops_them() -> None:
    event: Event[int] = Event("test")
    seen: list[tuple[str, int]] = []

    def first(value: int) -> None:
        seen.append(("first", value))

    def second(value: int) -> None:
        seen.append(("second", value))

    event.connect(first)
    event.connect(second)
    event.connect(first)            # connecting twice doesn't call twice
    event.emit(1)
    event.disconnect(first)
    event.emit(2)

    assert seen == [("first", 1), ("second", 1), ("second", 2)]
    assert len(event) == 1


def test_a_failing_handler_does_not_stop_the_others() -> None:
    event: Event[str] = Event("test")
    seen: list[str] = []

    def broken(_value: str) -> None:
        raise RuntimeError("subscriber bug")

    event.connect(broken)
    event.connect(seen.append)
    event.emit("still delivered")

    assert seen == ["still delivered"]


def test_backend_imports_without_pyside6() -> None:
    code = (
        "import sys; sys.modules['PySide6'] = None\n"
        "import core.async_runtime, core.events, transfers.transfer_manager, transfers.remote_transfer\n"
        "from transfers.transfer_manager import TransferManager; TransferManager()\n"
        "print('ok')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(APP_ROOT)}
    done = subprocess.run([sys.executable, "-c", code], cwd=APP_ROOT, env=env, capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_transfer_manager_events_reach_qt_slots_on_the_gui_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QObject, QThread, Slot

    from transfers.transfer_manager import TransferManager
    from ui.qt_bridge import QtTransferSignals

    app = QCoreApplication.instance() or QCoreApplication([])

    class Receiver(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, bool]] = []

        @Slot(str)
        def on_batch(self, batch_id: str) -> None:
            self.calls.append((batch_id, QThread.currentThread() is app.thread()))

    manager = TransferManager()
    bridge = QtTransferSignals(manager)
    receiver = Receiver()
    bridge.batch_finished.connect(receiver.on_batch)

    worker = threading.Thread(target=manager.batch_finished.emit, args=("batch-1",))   # like the asyncio thread
    worker.start()
    worker.join()
    assert receiver.calls == []          # queued, not run on the worker thread
    app.processEvents()

    assert receiver.calls == [("batch-1", True)]
    bridge.detach()
    assert len(manager.batch_finished) == 0
