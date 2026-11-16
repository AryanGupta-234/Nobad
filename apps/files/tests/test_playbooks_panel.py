from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from storage.app_data import AppDataService
from ui.playbooks_components import (
    NewSnippetDialog,
    PlaybookCardWidget,
    PlaybookExecutionDock,
    PlaybookInspectorWidget,
    PlaybooksSidebar,
    clean_terminal_output,
)
from ui.playbooks_panel import PlaybooksPanel


class TestPlaybooksPanelUI(unittest.TestCase):
    def setUp(self) -> None:
        self.app_data = AppDataService.create(":memory:")
        self.panel = PlaybooksPanel(self.app_data)
        self.panel.show()

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_clean_terminal_output(self) -> None:
        raw_ansi = "\x1B[32m[OK]\x1B[0m Service restarted.\r\n"
        cleaned = clean_terminal_output(raw_ansi)
        self.assertEqual(cleaned, "[OK] Service restarted.\n")

    def test_panel_initialization(self) -> None:
        self.assertIsNotNone(self.panel.sidebar)
        self.assertIsNotNone(self.panel.inspector)
        self.assertIsNotNone(self.panel.dock)
        self.assertFalse(self.panel.dock.isVisible())  # Hidden initially
        self.assertGreaterEqual(len(self.panel._recipes), 7)

    def test_search_filtering(self) -> None:
        # Search for "certbot"
        self.panel.search_input.setText("certbot")
        matching_cards = list(self.panel._card_widgets.values())
        self.assertGreaterEqual(len(matching_cards), 1)
        self.assertIn("certbot", matching_cards[0].recipe.id)

        # Clear search
        self.panel.search_input.setText("")
        self.assertGreaterEqual(len(self.panel._card_widgets), 7)

    def test_category_filtering(self) -> None:
        self.panel._on_category_changed("docker")
        self.assertEqual(self.panel._active_category, "docker")
        for card in self.panel._card_widgets.values():
            self.assertEqual(str(card.recipe.category), "docker")

    def test_connection_state_updates_inspector(self) -> None:
        mock_conn = MagicMock()
        mock_conn.host = "72.61.251.114"
        mock_conn.raw_connection = MagicMock()

        self.panel.set_connection(mock_conn)
        self.assertTrue(self.panel.inspector.run_cta.isEnabled())
        self.assertIn("72.61.251.114", self.panel.inspector.conn_note.text())

        # Disconnect
        self.panel.set_connection(None)
        self.assertFalse(self.panel.inspector.run_cta.isEnabled())
        self.assertIn("Disconnected", self.panel.inspector.conn_note.text())

    def test_execution_dock_flow(self) -> None:
        dock = self.panel.dock
        dock.start_execution("72.61.251.114", ["Step 1", "Step 2"])
        self.assertIn("Running", dock.status_pill.text())

        dock.append_output("Running task...\n")
        self.assertIn("Running task...", dock.console.toPlainText())

        dock.finish_execution(0, 3200, "Done")
        self.assertIn("Completed", dock.status_pill.text())
        self.assertIn("3.2s", dock.timer_lbl.text())

    def test_new_snippet_creation(self) -> None:
        dialog = NewSnippetDialog(self.panel)
        dialog.title_input.setText("Custom Health Ping")
        dialog.desc_input.setText("Pings health endpoint")
        dialog.script_input.setPlainText("curl -sSf http://localhost:8080/health")
        recipe = dialog.build_recipe()

        self.assertEqual(recipe.title, "Custom Health Ping")
        self.assertIn("curl", recipe.script_template)
        dialog.deleteLater()

    def test_fork_and_persistence_across_restart(self) -> None:
        # Fork certbot-ssl
        self.panel._fork_recipe("certbot-ssl")
        forked = self.panel._recipes[0]
        self.assertTrue(forked.title.endswith("(Custom)"))
        self.assertFalse(forked.is_prebundled)

        # Simulate app restart: create a new panel with the same storage
        restarted_panel = PlaybooksPanel(self.app_data)
        top_recipe = restarted_panel._recipes[0]
        self.assertEqual(top_recipe.id, forked.id)
        self.assertEqual(top_recipe.title, forked.title)
        restarted_panel.deleteLater()

    def test_delete_custom_snippet(self) -> None:
        # Fork first
        self.panel._fork_recipe("clean-disk")
        forked_id = self.panel._recipes[0].id

        # Delete with mock QMessageBox.question
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.panel._delete_recipe(forked_id)

        # Verify removed from memory
        self.assertNotIn(forked_id, {r.id for r in self.panel._recipes})

        # Verify removed from DB
        with self.app_data.session_factory() as session:
            repo = self.app_data.playbooks(session)
            self.assertIsNone(repo.get_snippet(forked_id))


if __name__ == "__main__":
    unittest.main()
