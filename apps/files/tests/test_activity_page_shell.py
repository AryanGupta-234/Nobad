from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.workbench_models import default_navigation_items


def test_activity_dock_lives_in_files_page_and_disconnect_is_in_workspace_bar(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    keys = [item.key for item in default_navigation_items()]
    assert "Activity" not in keys
    assert "Transfers" not in keys
    assert window.menuBar().cornerWidget() is None
    assert window.connection_status_bar.disconnect_button is window.disconnect_button
    assert not window.disconnect_button.isEnabled()
    assert window.activity_page is window.bottom_dock
    assert window.bottom_dock.transfer_panel is window.transfer_panel
    assert window.bottom_dock.logs_panel is window.logs_panel

    window._show_activity("Logs", navigate=True)
    assert window._current_page_key() == "Files"
    assert window.bottom_dock.active_tab() == "Logs & Diagnostics"

    window._show_activity("Transfers", navigate=True)
    assert window.bottom_dock.active_tab() == "Active Transfers"

    window.close()
    app.processEvents()
