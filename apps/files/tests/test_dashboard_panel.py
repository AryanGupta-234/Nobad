from __future__ import annotations

import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from core.health_monitor import (
    DiskMountInfo,
    ProcessInfo,
    ServerHealthCollector,
    ServerMetricsSnapshot,
)
from tests.test_health_monitor import MOCK_BATCH_OUTPUT_1
from ui.dashboard_components import (
    DiskMountsWidget,
    DiskSpaceConsumersWidget,
    MetricCardWidget,
    ProcessTableWidget,
    SparklineWidget,
)
from ui.dashboard_panel import DashboardPanel


app = QApplication.instance()
if app is None:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication([])


class TestDashboardPanel(unittest.TestCase):
    def setUp(self) -> None:
        self.collector = ServerHealthCollector()
        self.snapshot = self.collector.parse_batch(MOCK_BATCH_OUTPUT_1, now=1000.0)
        self.panel = DashboardPanel()

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_dashboard_components_initialized(self) -> None:
        self.assertIsNotNone(self.panel.card_cpu)
        self.assertIsNotNone(self.panel.card_mem)
        self.assertIsNotNone(self.panel.card_disk)
        self.assertIsNotNone(self.panel.card_net)
        self.assertIsNotNone(self.panel.process_table)
        self.assertIsNotNone(self.panel.mounts_widget)
        self.assertIsNotNone(self.panel.consumers_widget)

    def test_sparkline_widget(self) -> None:
        spark = SparklineWidget(line_color="#6366f1", max_points=20)
        spark.resize(200, 38)
        spark.set_values([10.0, 20.0, 35.0, 25.0, 40.0])
        self.assertEqual(len(spark._history), 5)
        spark.add_value(50.0)
        self.assertEqual(len(spark._history), 6)
        spark.clear()
        self.assertEqual(len(spark._history), 0)
        spark.deleteLater()

    def test_update_ui_with_snapshot(self) -> None:
        self.panel.stack.setCurrentIndex(1)
        self.panel._update_ui_with_snapshot(self.snapshot)

        # Check CPU Card
        self.assertEqual(self.panel.card_cpu.val_label.text(), f"{self.snapshot.cpu_percent:.1f}%")
        self.assertIn("Cores", self.panel.card_cpu.badge_label.text())

        # Check Memory Card
        self.assertIn("GB", self.panel.card_mem.val_label.text())

        # Check Disk Card
        self.assertIn("GB", self.panel.card_disk.val_label.text())
        self.assertEqual(self.panel.card_disk.badge_label.text(), "Root /")

        # Check Network Card
        self.assertIn("↓", self.panel.card_net.val_label.text())
        self.assertEqual(self.panel.card_net.badge_label.text(), "eth0")

        # Check Process Table
        self.assertEqual(self.panel.process_table.table.rowCount(), 3)
        self.assertEqual(self.panel.process_table.table.item(0, 0).text(), "14201")
        self.assertEqual(self.panel.process_table.table.item(0, 1).text(), "www-data")

        # Test process table search filter
        self.panel.process_table._on_search_changed("nginx")
        self.assertEqual(self.panel.process_table.table.rowCount(), 1)
        self.assertEqual(self.panel.process_table.table.item(0, 0).text(), "14201")

        self.panel.process_table._on_search_changed("nonexistent_process_xyz")
        self.assertEqual(self.panel.process_table.table.rowCount(), 0)

        self.panel.process_table._on_search_changed("")
        self.assertEqual(self.panel.process_table.table.rowCount(), 3)

        # Check Mounts Widget
        self.assertEqual(len(self.snapshot.mounts), 3)
        self.assertGreater(self.panel.mounts_widget.items_container.count(), 0)


if __name__ == "__main__":
    unittest.main()
