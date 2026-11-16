from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from PySide6.QtWidgets import QApplication

from editor.syntax import all_supported_languages, language_for_path
from ui.code_editor import CodeEditorWidget
from ui.editor_panel import EditorPanel, LanguageModeDialog


app = QApplication.instance() or QApplication([])


class TestEditorStudio(unittest.TestCase):
    def test_tier1_exact_filenames(self) -> None:
        self.assertEqual(language_for_path("Dockerfile"), "dockerfile")
        self.assertEqual(language_for_path("/app/Containerfile"), "dockerfile")
        self.assertEqual(language_for_path("docker-compose.yml"), "yaml")
        self.assertEqual(language_for_path("compose.yaml"), "yaml")
        self.assertEqual(language_for_path("Makefile"), "makefile")
        self.assertEqual(language_for_path("nginx.conf"), "nginx")
        self.assertEqual(language_for_path(".env"), "properties")
        self.assertEqual(language_for_path(".env.production"), "properties")
        self.assertEqual(language_for_path(".bashrc"), "shell")
        self.assertEqual(language_for_path(".zshrc"), "shell")
        self.assertEqual(language_for_path("Cargo.toml"), "toml")
        self.assertEqual(language_for_path("package.json"), "json")

    def test_tier2_extensions(self) -> None:
        self.assertEqual(language_for_path("main.py"), "python")
        self.assertEqual(language_for_path("app.ts"), "typescript")
        self.assertEqual(language_for_path("index.tsx"), "typescript")
        self.assertEqual(language_for_path("index.js"), "javascript")
        self.assertEqual(language_for_path("main.rs"), "rust")
        self.assertEqual(language_for_path("server.go"), "go")
        self.assertEqual(language_for_path("main.c"), "c")
        self.assertEqual(language_for_path("app.cpp"), "cpp")
        self.assertEqual(language_for_path("query.sql"), "sql")
        self.assertEqual(language_for_path("index.html"), "html")
        self.assertEqual(language_for_path("styles.css"), "css")
        self.assertEqual(language_for_path("styles.scss"), "scss")
        self.assertEqual(language_for_path("README.md"), "markdown")
        self.assertEqual(language_for_path("nginx.service"), "ini")

    def test_tier3_shebang_detection(self) -> None:
        self.assertEqual(language_for_path("custom-script", first_line="#!/usr/bin/env python3"), "python")
        self.assertEqual(language_for_path("deploy", first_line="#!/bin/bash"), "shell")
        self.assertEqual(language_for_path("runner", first_line="#!/usr/bin/node"), "javascript")
        self.assertEqual(language_for_path("test", first_line="#!/usr/bin/env perl"), "perl")

    def test_tier4_content_heuristics(self) -> None:
        self.assertEqual(language_for_path("unknown", content_sample="<?php echo 'hello';"), "php")
        self.assertEqual(language_for_path("unknown", content_sample="<!DOCTYPE html><html></html>"), "html")
        self.assertEqual(language_for_path("unknown", content_sample="<?xml version='1.0'?>"), "xml")
        self.assertEqual(language_for_path("unknown", content_sample="[Unit]\nDescription=Test"), "ini")
        self.assertEqual(language_for_path("unknown", content_sample='{"status": 200, "ok": true}'), "json")
        self.assertEqual(language_for_path("unknown", content_sample="plain regular text"), "plaintext")

    def test_all_supported_languages_list(self) -> None:
        langs = all_supported_languages()
        self.assertGreaterEqual(len(langs), 20)
        lang_ids = [l["id"] for l in langs]
        self.assertIn("python", lang_ids)
        self.assertIn("yaml", lang_ids)
        self.assertIn("dockerfile", lang_ids)
        self.assertIn("shell", lang_ids)
        self.assertIn("rust", lang_ids)
        self.assertIn("go", lang_ids)

    def test_code_editor_widget(self) -> None:
        editor = CodeEditorWidget(path="test.py", text="def hello():\n    return 42\n")
        self.assertEqual(editor.language(), "python")
        self.assertEqual(editor.text(), "def hello():\n    return 42\n")

        # Test text updates and replacement
        editor.set_text("a = 1\nb = 2\n")
        self.assertEqual(editor.text(), "a = 1\nb = 2\n")
        count = editor.replace_all("b = 2", "b = 99")
        self.assertEqual(count, 1)
        self.assertIn("b = 99", editor.text())

        # Test language switching
        editor.set_language("yaml")
        self.assertEqual(editor.language(), "yaml")

    def test_editor_panel_open_local_file(self) -> None:
        panel = EditorPanel()
        panel.resize(1024, 600)

        with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
            f.write("print('Hello from test!')\n")
            temp_path = f.name

        try:
            panel.open_local_file(temp_path)
            self.assertEqual(panel.tabs.count(), 1)
            editor = panel.current_editor()
            self.assertIsNotNone(editor)
            self.assertEqual(editor.language(), "python")
            self.assertIn("Hello from test!", editor.text())

            # Check HUD and status bar
            self.assertIn("tmp", panel.breadcrumb_path.text().lower())
            self.assertIn(panel.encoding_label.text(), ["UTF-8", "ASCII"])
            self.assertIn("PYTHON", panel.lang_mode_btn.text())
            self.assertEqual(panel.dirty_badge.text(), "✓ In Sync")

            # Check marking dirty
            panel._mark_dirty(editor)
            self.assertIn("Unsaved Edits", panel.dirty_badge.text())

            # Check clean title
            panel._set_clean_title(editor)
            self.assertEqual(panel.dirty_badge.text(), "✓ In Sync")

            # Close tab
            panel.close_all()
            self.assertEqual(panel.tabs.count(), 0)
            self.assertEqual(panel.breadcrumb_path.text(), "No file open")
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_editor_stack_layout_geometry(self) -> None:
        panel = EditorPanel()
        panel.resize(1024, 600)
        panel.show()

        with tempfile.NamedTemporaryFile("w+", suffix=".js", delete=False) as f:
            f.write("console.log('test geometry');\n")
            p1 = f.name
        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as f:
            f.write("version: '3.8'\nservices:\n  app:\n    image: nginx\n")
            p2 = f.name

        try:
            panel.open_local_file(p1)
            panel.open_local_file(p2)
            self.assertEqual(panel.tabs.count(), 2)

            # Check that editor widget is inside editor_stack with proper stretch
            editor2 = panel.current_editor()
            self.assertIsNotNone(editor2)
            self.assertEqual(editor2.language(), "yaml")
            self.assertIs(editor2.parent(), panel.editor_stack)

            # Switch back to tab 0
            panel.tabs.setCurrentIndex(0)
            editor1 = panel.current_editor()
            self.assertIsNotNone(editor1)
            self.assertEqual(editor1.language(), "javascript")
            self.assertIn("test geometry", editor1.text())

            # Close tab 0
            panel.close_tab(0)
            self.assertEqual(panel.tabs.count(), 1)
            self.assertEqual(panel.current_editor().language(), "yaml")
        finally:
            Path(p1).unlink(missing_ok=True)
            Path(p2).unlink(missing_ok=True)

    def test_language_mode_dialog(self) -> None:
        dlg = LanguageModeDialog("python")
        self.assertGreater(dlg.list_widget.count(), 10)
        dlg._on_search("rust")
        self.assertEqual(dlg.list_widget.count(), 1)
        lang_id, lang_name = dlg.get_selected_language()
        self.assertEqual(lang_id, "rust")


if __name__ == "__main__":
    unittest.main()
