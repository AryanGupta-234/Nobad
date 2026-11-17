"""The transfer backend has no UI toolkit in it: events are plain callbacks, safe across threads."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
