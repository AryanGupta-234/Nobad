from __future__ import annotations

import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from core.services_manager import SystemdServicesCollector
from tests.test_services_manager import (
    MOCK_JOURNAL_OUTPUT,
    MOCK_LIST_UNITS_OUTPUT,
    MOCK_PROPERTIES_OUTPUT,
)
from ui.services_components import (
    NewUnitModalDialog,
    ServiceCardWidget,
    ServiceDenseTableView,
    ServiceInspectorWidget,
)
from ui.services_panel import ServicesPanel

app = QApplication.instance()
if app is None:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication([])


class TestServicesPanel(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = SystemdServicesCollector.parse_inventory(MOCK_LIST_UNITS_OUTPUT, now=1000.0)
        self.panel = ServicesPanel()

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_services_components_initialized(self) -> None:
        self.assertIsNotNone(self.panel.header)
        self.assertIsNotNone(self.panel.inspector)
        self.assertIsNotNone(self.panel.dense_table)
        self.assertIsNotNone(self.panel.search_input)
        self.assertEqual(self.panel.stack.currentIndex(), 0)  # Starts in empty state

    def test_render_inventory(self) -> None:
        self.panel._snapshot = self.snapshot
        self.panel._render_inventory(self.snapshot)

        # Verify KPI badges updated
        self.assertEqual(self.panel.kpi_total.text(), "Total: 8")
        self.assertEqual(self.panel.kpi_running.text(), "● Running: 6")
        self.assertEqual(self.panel.kpi_failed.text(), "● Failed: 1")
        self.assertEqual(self.panel.kpi_stopped.text(), "Stopped: 1")
        self.assertEqual(self.panel.kpi_boot.text(), "★ Boot Enabled: 7")

        # Verify cards created
        self.assertGreater(self.panel.cards_layout.count(), 1)

        # Verify dense table populated
        self.assertEqual(self.panel.dense_table.rowCount(), 8)

    def test_filter_services_by_search(self) -> None:
        self.panel._snapshot = self.snapshot
        self.panel._search_query = "nginx"
        filtered = self.panel._get_filtered_services()
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].name, "nginx.service")

    def test_filter_services_by_category(self) -> None:
        self.panel._snapshot = self.snapshot
        self.panel._active_category = "database"
        filtered = self.panel._get_filtered_services()
        # postgresql and redis
        self.assertEqual(len(filtered), 2)
        names = {s.name for s in filtered}
        self.assertIn("postgresql.service", names)
        self.assertIn("redis-server.service", names)

    def test_inspector_widget(self) -> None:
        nginx = next(s for s in self.snapshot.services if s.name == "nginx.service")
        props = SystemdServicesCollector.parse_properties(MOCK_PROPERTIES_OUTPUT)
        logs = SystemdServicesCollector.parse_journal(MOCK_JOURNAL_OUTPUT)

        self.panel.inspector.set_service(nginx, props)
        self.panel.inspector.console.set_logs(nginx.name, logs)

        self.assertEqual(self.panel.inspector.title_label.text(), "nginx.service")
        self.assertIn("14201", self.panel.inspector.pid_val.text())
        self.assertEqual(len(self.panel.inspector.console._raw_entries), 7)

    def test_on_props_and_logs_received_dict_and_tuple(self) -> None:
        self.panel._snapshot = self.snapshot
        self.panel._selected_unit = "nginx.service"
        props = SystemdServicesCollector.parse_properties(MOCK_PROPERTIES_OUTPUT)
        logs = SystemdServicesCollector.parse_journal(MOCK_JOURNAL_OUTPUT)

        # Pass parsed dict directly as returned by fetch_unit_properties
        self.panel._on_props_received("nginx.service", props)
        self.assertIn("14201", self.panel.inspector.pid_val.text())
        self.assertIn("always", self.panel.inspector.restart_val.text())

        # Pass parsed tuple directly as returned by fetch_unit_logs
        self.panel._on_logs_received("nginx.service", logs)
        self.assertEqual(len(self.panel.inspector.console._raw_entries), 7)

    def test_new_unit_dialog(self) -> None:
        dlg = NewUnitModalDialog()
        self.assertEqual(dlg.unit_name, "fastapi-backend.service")
        self.assertIn("[Unit]", dlg.unit_content)
        self.assertTrue(dlg.enable_and_start)
        dlg.deleteLater()

    def test_edit_unit_from_inspector(self) -> None:
        nginx = next(s for s in self.snapshot.services if s.name == "nginx.service")
        props = {"FragmentPath": "/lib/systemd/system/nginx.service"}

        self.panel.inspector.set_service(nginx, props)
        self.assertEqual(self.panel.inspector._current_unit_path, "/lib/systemd/system/nginx.service")

        received: list[str] = []
        self.panel.edit_unit_requested.connect(received.append)

        # Trigger inspector edit button
        self.panel.inspector.edit_btn.click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], "/lib/systemd/system/nginx.service")

    def test_edit_unit_from_card_and_table(self) -> None:
        self.panel._snapshot = self.snapshot
        self.panel._render_inventory(self.snapshot)

        received: list[str] = []
        self.panel.edit_unit_requested.connect(received.append)

        # 1. Edit via Card
        first_card = self.panel.cards_layout.itemAt(0).widget()
        self.assertIsInstance(first_card, ServiceCardWidget)
        first_card.edit_requested.emit(first_card._service.name)

        self.assertEqual(len(received), 1)
        self.assertTrue(received[0].startswith("/lib/systemd/system/"))
        self.assertIn(first_card._service.name, received[0])

        # 2. Edit via Dense Table
        received.clear()
        self.panel.dense_table.edit_requested.emit("nginx.service")
        self.assertEqual(received, ["/lib/systemd/system/nginx.service"])


if __name__ == "__main__":
    unittest.main()
