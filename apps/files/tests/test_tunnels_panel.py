from __future__ import annotations

import sys
from unittest import TestCase
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.tunnel_manager import TunnelConfig, TunnelSessionInfo, TunnelStatus, TunnelType
from ui.tunnel_components import (
    NewTunnelModalDialog,
    TunnelCardWidget,
    TunnelDenseTableView,
    TunnelInspectorWidget,
)
from ui.tunnels_panel import TunnelsPanel

# Ensure singleton QApplication for testing
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestTunnelsPanel(TestCase):
    def setUp(self) -> None:
        self.panel = TunnelsPanel()
        self.panel.resize(1100, 750)

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_empty_state_and_connect_signal(self) -> None:
        self.assertEqual(self.panel.stack.currentIndex(), 0)
        signal_received = []
        self.panel.connect_requested.connect(lambda: signal_received.append(True))

        empty_view = self.panel.stack.widget(0)
        connect_btn = empty_view.findChild(type(self.panel.header.new_btn))
        self.assertIsNotNone(connect_btn)
        connect_btn.click()
        self.assertTrue(signal_received)

    def test_connected_state_and_rendering(self) -> None:
        mock_conn = MagicMock()
        mock_profile = MagicMock()
        mock_profile.name = "Production Server"
        mock_profile.host = "72.61.251.114"
        mock_profile.username = "root"
        mock_profile.port = 22

        self.panel.set_connection(mock_conn, mock_profile)
        self.assertEqual(self.panel.stack.currentIndex(), 1)
        self.assertIn("Production Server", self.panel.header.meta_label.text())

        # Check default tunnels populated
        self.assertGreaterEqual(len(self.panel._tunnel_configs), 5)
        # KPI Active card
        self.assertEqual(self.panel.kpi_active.val_lbl.text(), "0 Active")

    def test_filter_by_type_chips(self) -> None:
        mock_conn = MagicMock()
        self.panel.set_connection(mock_conn)

        # Filter by SOCKS5
        self.panel._set_type_filter("socks5")
        filtered = self.panel._get_filtered_sessions()
        self.assertTrue(all(s.config.tunnel_type == TunnelType.DYNAMIC_SOCKS5 for s in filtered))
        self.assertGreaterEqual(len(filtered), 1)

        # Filter by Local
        self.panel._set_type_filter("local")
        filtered_local = self.panel._get_filtered_sessions()
        self.assertTrue(all(s.config.tunnel_type == TunnelType.LOCAL for s in filtered_local))

        # Reset to All
        self.panel._set_type_filter("all")
        self.assertEqual(len(self.panel._get_filtered_sessions()), len(self.panel._tunnel_configs))

    def test_filter_by_search_query(self) -> None:
        mock_conn = MagicMock()
        self.panel.set_connection(mock_conn)

        # Search for Postgres
        self.panel._on_search_changed("postgres")
        filtered = self.panel._get_filtered_sessions()
        self.assertTrue(any("postgres" in s.config.name.lower() for s in filtered))

        # Search by port
        self.panel._on_search_changed("5433")
        filtered_port = self.panel._get_filtered_sessions()
        self.assertTrue(any(s.config.local_port == 5433 for s in filtered_port))

    def test_view_mode_switching(self) -> None:
        mock_conn = MagicMock()
        self.panel.set_connection(mock_conn)

        # Default is Split View (index 0)
        self.assertEqual(self.panel.view_stack.currentIndex(), 0)

        # Switch to Dense Table View
        self.panel._on_view_changed("table")
        self.assertEqual(self.panel.view_stack.currentIndex(), 1)

        # Switch back to Split View
        self.panel._on_view_changed("split")
        self.assertEqual(self.panel.view_stack.currentIndex(), 0)

    def test_tunnel_card_selection_and_inspector(self) -> None:
        mock_conn = MagicMock()
        mock_profile = MagicMock()
        mock_profile.host = "server.net"
        mock_profile.username = "admin"
        mock_profile.port = 22

        self.panel.set_connection(mock_conn, mock_profile)
        first_id = self.panel._tunnel_configs[0].id
        self.panel._select_tunnel(first_id)

        self.assertEqual(self.panel._selected_tunnel_id, first_id)
        self.assertEqual(self.panel.inspector.title_label.text(), self.panel._tunnel_configs[0].name)
        self.assertIn("ssh -N", self.panel.inspector.cli_command_label.text())

    def test_new_tunnel_modal_dialog(self) -> None:
        dlg = NewTunnelModalDialog()
        self.assertEqual(dlg.local_host_input.text(), "127.0.0.1")

        # Test SOCKS5 mode disabling remote fields
        dlg.card_socks.setChecked(True)
        self.assertFalse(dlg.remote_host_input.isEnabled())
        self.assertFalse(dlg.remote_port_input.isEnabled())

        # Switch back to local
        dlg.card_local.setChecked(True)
        self.assertTrue(dlg.remote_host_input.isEnabled())

        cfg = dlg.get_config()
        self.assertEqual(cfg.tunnel_type, TunnelType.LOCAL)
        dlg.deleteLater()

    def test_tunnel_toggle_execution_with_async_worker(self) -> None:
        mock_conn = MagicMock()
        mock_listener = MagicMock()
        mock_conn.forward_local_port.return_value = mock_listener

        self.panel.set_connection(mock_conn)
        target_id = self.panel._tunnel_configs[0].id

        with patch.object(self.panel._tunnel_mgr, "is_port_in_use", return_value=False):
            with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                self.panel._on_tunnel_toggle(target_id, True)

                # Process Qt events to let worker complete
                for _ in range(50):
                    app.processEvents()

                # Verify worker succeeded without raising TypeError
                self.assertFalse(mock_warn.called)
                sess = self.panel._tunnel_mgr.get_session(target_id)
                self.assertIsNotNone(sess)
                self.assertEqual(sess.status, TunnelStatus.ACTIVE)

    def test_tunnel_ping_execution_with_async_worker(self) -> None:
        mock_conn = MagicMock()
        self.panel.set_connection(mock_conn)
        target_id = self.panel._tunnel_configs[0].id

        with patch("core.tunnel_manager.SSHTunnelManager.test_socket_ping", return_value=(True, 12.4, "OK")):
            self.panel._on_tunnel_ping(target_id)
            for _ in range(50):
                app.processEvents()

            sess = self.panel._tunnel_mgr.get_session(target_id)
            self.assertIsNotNone(sess)
            self.assertEqual(sess.latency_ms, 12.4)

    def test_tunnel_delete_execution(self) -> None:
        mock_conn = MagicMock()
        self.panel.set_connection(mock_conn)
        initial_count = len(self.panel._tunnel_configs)
        target_id = self.panel._tunnel_configs[0].id

        from PySide6.QtWidgets import QDialog
        with patch("ui.tunnels_panel.ConfirmDeleteTunnelDialog.exec", return_value=QDialog.DialogCode.Accepted):
            self.panel._on_tunnel_delete(target_id)
            self.assertEqual(len(self.panel._tunnel_configs), initial_count - 1)
            self.assertFalse(any(c.id == target_id for c in self.panel._tunnel_configs))

    def test_tunnel_error_dialog_port_collision_resolution(self) -> None:
        mock_conn = MagicMock()
        self.panel.set_connection(mock_conn)
        target_id = self.panel._tunnel_configs[0].id
        cfg = next(c for c in self.panel._tunnel_configs if c.id == target_id)
        original_port = cfg.local_port

        from core.result import OperationResult
        from PySide6.QtWidgets import QDialog

        def accept_with_suggestion(dlg_inst):
            dlg_inst.action_use_suggested = True
            return QDialog.DialogCode.Accepted

        with patch("ui.tunnels_panel.SSHTunnelManager.find_next_available_port", return_value=original_port + 1):
            fail_res = OperationResult.failure(
                f"Port collision: Local port {original_port} is already in use by another application.",
                technical_details=f"port_collision: host=127.0.0.1 port={original_port} suggested={original_port + 1}",
            )
            with patch.object(self.panel, "_on_tunnel_toggle") as mock_toggle:
                with patch.object(self.panel, "show"):
                    with patch("ui.tunnels_panel.TunnelErrorDialog.exec", side_effect=lambda: QDialog.DialogCode.Accepted):
                        with patch.object(self.panel, "_select_tunnel"):
                            pass
                with patch("ui.tunnels_panel.TunnelErrorDialog.exec", side_effect=lambda: accept_with_suggestion(mock_dlg_instance)):
                    pass

        # Direct verification of port suggestion flow:
        with patch("ui.tunnels_panel.TunnelErrorDialog") as MockDialogClass:
            mock_dlg = MagicMock()
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.action_use_suggested = True
            MockDialogClass.return_value = mock_dlg

            with patch("ui.tunnels_panel.SSHTunnelManager.find_next_available_port", return_value=original_port + 1):
                fail_res = OperationResult.failure(
                    f"Port collision: Local port {original_port} is already in use by another application.",
                    technical_details=f"port_collision: host=127.0.0.1 port={original_port} suggested={original_port + 1}",
                )
                with patch.object(self.panel, "_on_tunnel_toggle") as mock_toggle:
                    self.panel._on_tunnel_action_finished(target_id, fail_res)
                    self.assertEqual(cfg.local_port, original_port + 1)
                    mock_toggle.assert_called_once_with(target_id, True)
