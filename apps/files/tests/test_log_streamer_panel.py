from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

# Ensure single QApplication instance
app = QApplication.instance() or QApplication([])

from core.log_streamer import LogEntry, LogSourceType, LogStreamConfig, LogStreamStatus
from ui.log_stream_pane import LogStreamPane
from ui.log_streamer_panel import LogStreamerPanel, NewLogStreamDialog


class TestLogStreamerPanelUI(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = LogStreamerPanel()
        self.panel.show()

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_panel_initialization(self) -> None:
        self.assertIsNotNone(self.panel.main_splitter)
        self.assertEqual(self.panel._current_layout, "split")
        self.assertEqual(self.panel.stack.currentIndex(), 0)  # Starts in disconnected empty view
        self.assertIn("0 Streams Live", self.panel.active_badge.text())
        self.assertIn("Disconnected", self.panel.host_badge.text())

    def test_connection_state_switches_stack(self) -> None:
        mock_conn = MagicMock()
        mock_profile = MagicMock(host="192.168.1.100", username="admin")
        self.panel.set_connection(mock_conn, mock_profile)
        self.assertEqual(self.panel.stack.currentIndex(), 1)
        self.assertIn("192.168.1.100", self.panel.host_badge.text())

        # Disconnect
        self.panel.set_connection(None)
        self.assertEqual(self.panel.stack.currentIndex(), 0)
        self.assertIn("Disconnected", self.panel.host_badge.text())

    def test_layout_switching(self) -> None:
        self.panel.stack.setCurrentIndex(1)
        # Apply a preset with 2 streams
        self.panel.apply_preset("nginx-dual")
        self.assertEqual(len(self.panel._panes), 2)

        # 1. Single Mode
        self.panel.set_layout_mode("single")
        self.assertEqual(self.panel._current_layout, "single")
        visible_panes = [p for p in self.panel._panes.values() if p.isVisible()]
        self.assertEqual(len(visible_panes), 1)

        # 2. Split Mode (2 columns)
        self.panel.set_layout_mode("split")
        self.assertEqual(self.panel._current_layout, "split")
        visible_panes = [p for p in self.panel._panes.values() if p.isVisible()]
        self.assertEqual(len(visible_panes), 2)

        # 3. Stacked Mode (2 rows)
        self.panel.set_layout_mode("stacked")
        self.assertEqual(self.panel._current_layout, "stacked")

        # 4. Quad Mode
        self.panel.set_layout_mode("quad")
        self.assertEqual(self.panel._current_layout, "quad")

        # 5. Switch back and forth between modes to ensure C++ objects are not deleted
        self.panel.set_layout_mode("split")
        self.assertEqual(self.panel._current_layout, "split")
        self.panel.set_layout_mode("single")
        self.assertEqual(self.panel._current_layout, "single")
        self.panel.set_layout_mode("quad")
        self.assertEqual(self.panel._current_layout, "quad")
        self.panel.set_layout_mode("stacked")
        self.assertEqual(self.panel._current_layout, "stacked")

    def test_preset_application(self) -> None:
        self.panel.apply_preset("security")
        self.assertEqual(len(self.panel._panes), 2)
        pane_names = [p.config.name for p in self.panel._panes.values()]
        self.assertIn("Auth / Security", pane_names)
        self.assertIn("System Syslog", pane_names)

    def test_pane_filtering_and_batch_flush(self) -> None:
        cfg = LogStreamConfig(name="Access Stream")
        pane = LogStreamPane(cfg)

        entry1 = LogEntry(
            timestamp="15:40:01",
            level="success",
            source="Access",
            text='10.0.0.1 GET /healthz 200',
            raw='10.0.0.1 GET /healthz 200',
            line_number=1,
            status_code=200,
            client_ip="10.0.0.1",
            method="GET",
            path="/healthz",
        )
        entry2 = LogEntry(
            timestamp="15:40:02",
            level="error",
            source="Access",
            text='10.0.0.2 POST /api/v1/checkout 502',
            raw='10.0.0.2 POST /api/v1/checkout 502',
            line_number=2,
            status_code=502,
            client_ip="10.0.0.2",
            method="POST",
            path="/api/v1/checkout",
        )

        pane.append_log_entry(entry1)
        pane.append_log_entry(entry2)
        pane._flush_batch_queue()

        self.assertEqual(pane._total_lines, 2)
        canvas_text = pane.canvas.toPlainText()
        self.assertIn("10.0.0.1", canvas_text)
        self.assertIn("10.0.0.2", canvas_text)

        # Test query filter
        pane._filter_query = "checkout"
        pane._rebuild_canvas()
        filtered_text = pane.canvas.toPlainText()
        self.assertNotIn("healthz", filtered_text)
        self.assertIn("checkout", filtered_text)

        # Test level filter: errors only
        pane._filter_query = ""
        pane._select_level("error")
        level_filtered = pane.canvas.toPlainText()
        self.assertNotIn("healthz", level_filtered)
        self.assertIn("502", level_filtered)

        pane.deleteLater()

    def test_sticky_auto_scroll(self) -> None:
        cfg = LogStreamConfig(name="Scroll Test")
        pane = LogStreamPane(cfg)
        pane.show()

        # Append lines to create scroll range
        for i in range(50):
            pane.append_log_entry(
                LogEntry(
                    timestamp="now",
                    level="info",
                    source="test",
                    text=f"Log line message number {i}",
                    raw=f"Log line message number {i}",
                    line_number=i,
                )
            )
        pane._flush_batch_queue()

        # Simulate user scrolling up
        pane.canvas.verticalScrollBar().setValue(0)
        pane._on_vertical_scroll(0)
        self.assertFalse(pane._auto_scroll)

        # New entry should not auto-scroll, floating pill should appear
        new_entry = LogEntry(
            timestamp="now",
            level="warn",
            source="test",
            text="New warning line",
            raw="New warning line",
            line_number=51,
        )
        pane.append_log_entry(new_entry)
        pane._flush_batch_queue()

        self.assertTrue(pane.floating_pill.isVisible())
        self.assertIn("Auto-scroll paused (1 new lines)", pane.floating_pill.text())

        # Clicking pill snaps to bottom and re-engages auto-scroll
        pane.jump_to_bottom()
        self.assertTrue(pane._auto_scroll)
        self.assertFalse(pane.floating_pill.isVisible())

        pane.deleteLater()

    def test_new_log_dialog(self) -> None:
        dlg = NewLogStreamDialog()
        self.assertEqual(dlg.name_input.text(), "Nginx Access")

        # Select MySQL preset
        for btn in dlg.preset_buttons:
            if "MySQL" in btn.text():
                btn.click()
                break

        cfg = dlg.get_config()
        self.assertIn("MySQL", cfg.name)
        self.assertEqual(cfg.target_path, "/var/log/mysql/error.log")
        self.assertEqual(cfg.source_type, LogSourceType.FILE)
        dlg.deleteLater()

    def test_no_connection_dialog_and_connect_signal(self) -> None:
        from ui.log_streamer_panel import LogStreamerNoConnectionDialog
        from PySide6.QtWidgets import QDialog
        from unittest.mock import patch

        signal_emitted = []
        self.panel.connect_requested.connect(lambda: signal_emitted.append(True))

        with patch.object(LogStreamerNoConnectionDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.panel.open_new_stream_dialog()
            self.assertEqual(len(signal_emitted), 1)

        with patch.object(LogStreamerNoConnectionDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.panel.apply_preset("security", notify_if_disconnected=True)
            self.assertEqual(len(signal_emitted), 2)


if __name__ == "__main__":
    unittest.main()
