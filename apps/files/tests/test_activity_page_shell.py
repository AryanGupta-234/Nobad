from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.workbench_models import default_navigation_items


def test_activity_page_replaces_bottom_dock_and_disconnect_is_in_workspace_bar(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    keys = [item.key for item in default_navigation_items()]
    assert "Activity" in keys
    assert "Transfers" not in keys
    assert "Logs" not in keys
    assert window.menuBar().cornerWidget() is None
    assert window.connection_status_bar.disconnect_button is window.disconnect_button
    assert not window.disconnect_button.isEnabled()
    assert window.activity_page.tabs.widget(0) is window.transfer_panel
    assert window.activity_page.tabs.widget(1) is window.logs_panel

    window._show_activity("Logs", navigate=True)
    assert window._current_page_key() == "Activity"
    assert window.activity_page.active_tab() == "Logs"

    window.close()
    app.processEvents()
