from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from core.result import OperationResult
from editor.editor_session import EditorSession
from editor.encoding import detect_encoding, is_probably_binary
from editor.remote_edit_manager import RemoteEditManager
from editor.syntax import all_supported_languages, language_for_path
from file_ops.temp_workspace import SecureTempWorkspace
from ui.async_worker import AsyncWorker
from ui.code_editor import CodeEditorWidget
from ui.diff_viewer import DiffViewerDialog
from ui.icons import get_icon


class LanguageModeDialog(QDialog):
    """Searchable command palette dialog to switch the active editor language mode."""

    def __init__(self, current_lang: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Language Mode")
        self.setFixedSize(440, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #121218;
                border: 1px solid #272738;
                border-radius: 10px;
            }
            QLabel {
                color: #a1a1aa;
                font-size: 11px;
            }
            QLineEdit {
                background-color: #181822;
                color: #f4f4f5;
                border: 1px solid #323248;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                font-family: 'JetBrains Mono', monospace;
            }
            QLineEdit:focus {
                border: 1px solid #6366f1;
            }
            QListWidget {
                background-color: #14141e;
                border: 1px solid #232334;
                border-radius: 6px;
                color: #f4f4f5;
                font-size: 12px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #1e1e2c;
            }
            QListWidget::item:selected {
                background-color: #4f46e5;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QLabel("Select Language Mode (Ctrl+K M)")
        header.setStyleSheet("font-size: 13px; font-weight: bold; color: #f4f4f5;")
        layout.addWidget(header)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter languages (e.g. Python, Docker, YAML, Shell)...")
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        self.all_langs = all_supported_languages()
        self._populate_list(self.all_langs, current_lang)

        self.search_input.textChanged.connect(self._on_search)
        self.list_widget.itemDoubleClicked.connect(self.accept)

        self.selected_lang_id = current_lang

    def _populate_list(self, langs: list[dict[str, str]], current_lang: str) -> None:
        self.list_widget.clear()
        selected_row = 0
        for idx, item in enumerate(langs):
            name = f"{item['icon']}  {item['name']} ({item['ext']})"
            list_item = QListWidgetItem(name)
            list_item.setData(Qt.ItemDataRole.UserRole, item["id"])
            list_item.setData(Qt.ItemDataRole.UserRole + 1, item["name"])
            self.list_widget.addItem(list_item)
            if item["id"] == current_lang:
                selected_row = idx
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(selected_row)

    def _on_search(self, query: str) -> None:
        q = query.lower().strip()
        filtered = [
            l for l in self.all_langs
            if q in l["name"].lower() or q in l["id"].lower() or q in l["ext"].lower()
        ]
        self._populate_list(filtered, self.selected_lang_id)

    def get_selected_language(self) -> tuple[str, str]:
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole), item.data(Qt.ItemDataRole.UserRole + 1)
        return "plaintext", "Plain Text"


class EditorPanel(QWidget):
    """
    Next-Gen Remote Monaco Code Editor Studio.
    Provides multi-tab editing, smart 5-tier language detection, remote metadata HUD,
    VS Code status bar, pre-upload diff reviews, and save-as-sudo privilege escalation.
    """

    log_requested = Signal(str, str)
    run_in_terminal_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("EditorPanel")
        self.setStyleSheet("QWidget#EditorPanel { background: #09090b; }")
        self.remote_ops: Any = None
        self.connection: Any = None
        self.workspace = SecureTempWorkspace()
        self.manager: RemoteEditManager | None = None
        self.sessions: dict[CodeEditorWidget, EditorSession] = {}
        self._workers: list[AsyncWorker] = []

        self._init_ui()

    def minimumSizeHint(self) -> QSize:
        return QSize(700, 300)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Bar: Tabs & Action Buttons
        top_bar = QFrame()
        top_bar.setObjectName("EditorTopBar")
        top_bar.setFixedHeight(38)
        top_bar.setStyleSheet("""
            QFrame#EditorTopBar {
                background: #111114;
                border-bottom: 1px solid #1e1e24;
            }
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 0, 10, 0)
        top_layout.setSpacing(8)

        # Tab Bar
        self.tabs = QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDrawBase(False)
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                background: #121216;
                color: #818cf8;
                border: 1px solid #1e1e24;
                border-bottom: 2px solid transparent;
                border-radius: 6px 6px 0 0;
                padding: 6px 14px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 11.5px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #181822;
                color: #f4f4f5;
                border-bottom: 2px solid #6366f1;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background: #161620;
                color: #e4e4e7;
            }
        """)
        top_layout.addWidget(self.tabs, 1)

        # Action Buttons
        self.run_terminal_btn = QPushButton("▷ Run in Terminal")
        self.run_terminal_btn.setToolTip("Run current script in embedded Terminal session")
        self.run_terminal_btn.setFixedHeight(26)
        self.run_terminal_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(16, 185, 129, 0.12);
                color: #34d399;
                border: 1px solid rgba(16, 185, 129, 0.3);
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(16, 185, 129, 0.22);
            }
        """)
        self.run_terminal_btn.clicked.connect(self._run_current_in_terminal)
        top_layout.addWidget(self.run_terminal_btn)

        self.format_btn = QPushButton("⟲ Format")
        self.format_btn.setToolTip("Format Document (Shift+Alt+F)")
        self.format_btn.setFixedHeight(26)
        self.format_btn.setStyleSheet("""
            QPushButton {
                background-color: #161620;
                color: #d4d4d8;
                border: 1px solid #232334;
                border-radius: 5px;
                padding: 0 9px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #20202e;
                color: #ffffff;
            }
        """)
        self.format_btn.clicked.connect(self._format_current)
        top_layout.addWidget(self.format_btn)

        self.diff_btn = QPushButton("Review Diff")
        self.diff_btn.setToolTip("Compare local buffer changes against remote server copy")
        self.diff_btn.setFixedHeight(26)
        self.diff_btn.setStyleSheet("""
            QPushButton {
                background-color: #161620;
                color: #818cf8;
                border: 1px solid #272738;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #20202e;
                color: #c7d2fe;
            }
        """)
        self.diff_btn.clicked.connect(self._review_current_diff)
        top_layout.addWidget(self.diff_btn)

        self.sudo_save_btn = QPushButton("Sudo Save")
        self.sudo_save_btn.setToolTip("Save protected file with sudo elevation (sudo tee)")
        self.sudo_save_btn.setFixedHeight(26)
        self.sudo_save_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(245, 158, 11, 0.12);
                color: #fbbf24;
                border: 1px solid rgba(245, 158, 11, 0.3);
                border-radius: 5px;
                padding: 0 9px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(245, 158, 11, 0.22);
            }
        """)
        self.sudo_save_btn.clicked.connect(self._save_sudo)
        top_layout.addWidget(self.sudo_save_btn)

        self.save_button = QPushButton("Save (Ctrl+S)")
        self.save_button.setIcon(get_icon("check", color="#ffffff", size=13))
        self.save_button.setFixedHeight(26)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #4f46e5;
                color: #ffffff;
                font-weight: bold;
                border-radius: 5px;
                padding: 0 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4338ca;
            }
        """)
        self.save_button.clicked.connect(self.save_current)
        top_layout.addWidget(self.save_button)

        main_layout.addWidget(top_bar)

        # 2. Breadcrumbs & Remote Metadata HUD
        hud_bar = QFrame()
        hud_bar.setObjectName("EditorHud")
        hud_bar.setFixedHeight(28)
        hud_bar.setStyleSheet("""
            QFrame#EditorHud {
                background: #0d0d12;
                border-bottom: 1px solid #191924;
            }
            QLabel {
                font-family: 'JetBrains Mono', monospace;
                font-size: 10.5px;
            }
        """)
        hud_layout = QHBoxLayout(hud_bar)
        hud_layout.setContentsMargins(12, 0, 12, 0)
        hud_layout.setSpacing(8)

        self.server_badge = QLabel("local")
        self.server_badge.setStyleSheet("""
            background-color: #14141e;
            color: #818cf8;
            border: 1px solid #232334;
            border-radius: 4px;
            padding: 1px 6px;
            font-weight: 600;
        """)
        hud_layout.addWidget(self.server_badge)

        hud_sep = QLabel("›")
        hud_sep.setStyleSheet("color: #52525b;")
        hud_layout.addWidget(hud_sep)

        self.breadcrumb_path = QLabel("No file open")
        self.breadcrumb_path.setStyleSheet("color: #d4d4d8; font-weight: 500;")
        hud_layout.addWidget(self.breadcrumb_path)

        hud_layout.addStretch()

        self.permissions_badge = QLabel("0644 (-rw-r--r--)")
        self.permissions_badge.setStyleSheet("""
            background-color: #121218;
            color: #a1a1aa;
            border: 1px solid #232334;
            border-radius: 4px;
            padding: 1px 6px;
        """)
        hud_layout.addWidget(self.permissions_badge)

        self.owner_badge = QLabel("root:root")
        self.owner_badge.setStyleSheet("color: #71717a;")
        hud_layout.addWidget(self.owner_badge)

        self.size_badge = QLabel("0 B")
        self.size_badge.setStyleSheet("color: #71717a;")
        hud_layout.addWidget(self.size_badge)

        self.dirty_badge = QLabel("✓ In Sync")
        self.dirty_badge.setStyleSheet("color: #10b981; font-weight: 600;")
        hud_layout.addWidget(self.dirty_badge)

        main_layout.addWidget(hud_bar)

        # 3. Central Canvas: Stack of Editors
        self.editor_stack = QStackedWidget()
        self.editor_stack.setObjectName("EditorStack")
        self.editor_stack.setStyleSheet("QStackedWidget#EditorStack { background: #09090b; }")

        # Empty state placeholder
        self.empty_placeholder = QWidget()
        empty_layout = QVBoxLayout(self.empty_placeholder)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label = QLabel("No File Open\nSelect a file from the explorer to open and edit")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setStyleSheet("color: #52525b; font-size: 13px; font-family: 'JetBrains Mono', monospace;")
        empty_layout.addWidget(empty_label)
        self.editor_stack.addWidget(self.empty_placeholder)

        main_layout.addWidget(self.editor_stack, 1)
        self.editor_container = self.editor_stack  # Backward-compatibility alias

        # 4. VS Code Status Bar
        status_bar = QFrame()
        status_bar.setObjectName("EditorStatusBar")
        status_bar.setFixedHeight(24)
        status_bar.setStyleSheet("""
            QFrame#EditorStatusBar {
                background: #101016;
                border-top: 1px solid #1a1a24;
            }
            QLabel {
                color: #a1a1aa;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10.5px;
            }
        """)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 0, 10, 0)
        status_layout.setSpacing(10)

        self.cursor_pos_label = QLabel("Ln 1, Col 1")
        self.cursor_pos_label.setStyleSheet("color: #d4d4d8;")
        status_layout.addWidget(self.cursor_pos_label)

        status_layout.addWidget(QLabel("|"))

        self.spaces_label = QLabel("Spaces: 4")
        status_layout.addWidget(self.spaces_label)

        status_layout.addWidget(QLabel("|"))

        self.encoding_label = QLabel("UTF-8")
        status_layout.addWidget(self.encoding_label)

        status_layout.addWidget(QLabel("|"))

        self.line_endings_label = QLabel("LF")
        status_layout.addWidget(self.line_endings_label)

        status_layout.addWidget(QLabel("|"))

        self.stats_label = QLabel("0 lines (0 chars)")
        status_layout.addWidget(self.stats_label)

        status_layout.addStretch()

        self.sync_status_label = QLabel("✓ In Sync with Server")
        self.sync_status_label.setStyleSheet("color: #10b981; font-weight: 500;")
        status_layout.addWidget(self.sync_status_label)

        status_layout.addStretch()

        # Language Mode Button
        self.lang_mode_btn = QPushButton("Plain Text ▾")
        self.lang_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_mode_btn.setFixedHeight(20)
        self.lang_mode_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #818cf8;
                border: 1px solid #232334;
                border-radius: 3px;
                padding: 0 7px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10.5px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1e1e2c;
                color: #c7d2fe;
            }
        """)
        self.lang_mode_btn.clicked.connect(self._open_language_selector)
        status_layout.addWidget(self.lang_mode_btn)

        main_layout.addWidget(status_bar)

        # Tab signals
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # --- Connection and Remote Ops ---

    def set_connection(self, connection: Any) -> None:
        self.connection = connection
        if connection and hasattr(connection, "profile"):
            self.server_badge.setText(connection.profile.name)
        else:
            self.server_badge.setText("local")

    def set_remote_ops(self, remote_ops: Any) -> None:
        self.remote_ops = remote_ops
        self.manager = RemoteEditManager(remote_ops, self.workspace)

    def clear_connection(self) -> None:
        self.remote_ops = None
        self.connection = None
        self.manager = None
        self.server_badge.setText("local")

    # --- File Open & Session Management ---

    def open_local_file(self, local_path: str) -> None:
        path = Path(local_path).expanduser()
        if not path.is_file():
            QMessageBox.warning(self, "Editor", "Choose a local file to edit.")
            return
        if is_probably_binary(path):
            QMessageBox.warning(self, "Editor", "This file appears to be binary and cannot be edited safely.")
            return
        encoding = detect_encoding(path)
        try:
            text = path.read_text(encoding=encoding)
        except Exception as exc:
            QMessageBox.warning(self, "Editor", f"Could not open file: {exc}")
            return
        session = EditorSession(local_path=path, encoding=encoding, readonly=not path.stat().st_mode & 0o200)
        self._add_session(session, text)

    def open_remote_file(self, remote_path: str) -> None:
        if self.manager is None:
            QMessageBox.information(self, "Editor unavailable", "Connect to a server before editing remote files.")
            return
        worker = AsyncWorker(lambda: self.manager.open_remote_file(remote_path))
        self._track_worker(worker)
        worker.succeeded.connect(self._add_remote_session)
        worker.failed.connect(self._show_error)
        worker.start()

    def _add_remote_session(self, result: OperationResult) -> None:
        session: EditorSession = result.data
        text = session.local_path.read_text(encoding=session.encoding)
        self._add_session(session, text)
        for warning in result.warnings:
            self.log_requested.emit(warning, "warning")

    def _add_session(self, session: EditorSession, text: str) -> None:
        editor = CodeEditorWidget(path=session.display_name, text=text, readonly=session.readonly)
        editor.changed.connect(lambda editor=editor: self._mark_dirty(editor))
        editor.cursor_changed.connect(self._on_cursor_moved)
        editor.save_requested.connect(self.save_current)

        self.sessions[editor] = session
        self.editor_stack.addWidget(editor)
        index = self.tabs.addTab(Path(session.display_name).name)
        self.tabs.setTabData(index, editor)
        self.tabs.setCurrentIndex(index)
        self.editor_stack.setCurrentWidget(editor)
        self._update_hud_and_status(session, editor)

    def current_editor(self) -> CodeEditorWidget | None:
        current = self.editor_stack.currentWidget()
        return current if isinstance(current, CodeEditorWidget) else None

    def _on_tab_changed(self, index: int) -> None:
        if index < 0 or index >= self.tabs.count():
            self.editor_stack.setCurrentWidget(self.empty_placeholder)
            self._clear_hud_and_status()
            return
        editor = self.tabs.tabData(index)
        if isinstance(editor, CodeEditorWidget):
            self.editor_stack.setCurrentWidget(editor)
            session = self.sessions.get(editor)
            if session:
                self._update_hud_and_status(session, editor)

    def _update_hud_and_status(self, session: EditorSession, editor: CodeEditorWidget) -> None:
        # Path & Breadcrumbs
        display_path = session.remote_path or str(session.local_path)
        self.breadcrumb_path.setText(display_path)

        # File size
        text = editor.text()
        byte_len = len(text.encode("utf-8"))
        size_str = f"{byte_len / 1024:.1f} KB" if byte_len >= 1024 else f"{byte_len} B"
        self.size_badge.setText(size_str)

        # Permissions
        if session.readonly:
            self.permissions_badge.setText("0444 [Read-Only]")
        else:
            self.permissions_badge.setText("0644 (-rw-r--r--)")

        # Encoding & Line Count
        self.encoding_label.setText(session.encoding.upper())
        lines = len(text.splitlines())
        chars = len(text)
        self.stats_label.setText(f"{lines} lines ({chars} chars)")

        # Sync Badge
        if session.dirty:
            self.dirty_badge.setText("⚡ Unsaved Edits")
            self.dirty_badge.setStyleSheet("color: #fbbf24; font-weight: 600;")
            self.sync_status_label.setText("⚡ Unsaved Edits in Buffer")
            self.sync_status_label.setStyleSheet("color: #fbbf24; font-weight: 500;")
        else:
            self.dirty_badge.setText("✓ In Sync")
            self.dirty_badge.setStyleSheet("color: #10b981; font-weight: 600;")
            self.sync_status_label.setText("✓ In Sync with Server")
            self.sync_status_label.setStyleSheet("color: #10b981; font-weight: 500;")

        # Language mode
        lang_id = editor.language()
        self.lang_mode_btn.setText(f"{lang_id.upper()} ▾")

    def _on_cursor_moved(self, line: int, col: int) -> None:
        self.cursor_pos_label.setText(f"Ln {line}, Col {col}")

    def _mark_dirty(self, editor: CodeEditorWidget) -> None:
        session = self.sessions.get(editor)
        if session is None:
            return
        session.dirty = True
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == editor:
                name = Path(session.display_name).name
                if not self.tabs.tabText(i).startswith("● "):
                    self.tabs.setTabText(i, f"● {name}")
                break
        self._update_hud_and_status(session, editor)

    def _set_clean_title(self, editor: CodeEditorWidget) -> None:
        session = self.sessions.get(editor)
        if session is None:
            return
        session.dirty = False
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == editor:
                self.tabs.setTabText(i, Path(session.display_name).name)
                break
        self._update_hud_and_status(session, editor)

    # --- Actions: Save, Sudo Save, Format, Diff, Terminal ---

    def save_current(self) -> None:
        editor = self.current_editor()
        if editor is not None:
            self._save_editor(editor)

    def _save_sudo(self) -> None:
        editor = self.current_editor()
        session = self.sessions.get(editor) if editor else None
        if editor is None or session is None:
            return
        if not session.remote_path:
            QMessageBox.information(self, "Sudo Save", "Sudo escalation is only needed for remote server files.")
            return

        resp = QMessageBox.question(
            self,
            "Sudo Elevation Required",
            f"Save {session.remote_path} with elevated privileges?\n\nThis writes the buffer securely using remote 'sudo tee'.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._save_remote(editor, session, force=True)

    def _save_editor(self, editor: CodeEditorWidget) -> None:
        session = self.sessions.get(editor)
        if session is None or session.readonly:
            return
        if session.remote_path:
            if self.manager is None:
                QMessageBox.information(self, "Editor unavailable", "Reconnect to the file's server before saving.")
                return
            self._save_remote(editor, session)
        else:
            self._save_local(editor, session)

    def _save_local(self, editor: CodeEditorWidget, session: EditorSession) -> None:
        try:
            session.local_path.write_text(editor.text(), encoding=session.encoding)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", f"Could not save local file: {exc}")
            return
        session.dirty = False
        self._set_clean_title(editor)
        self.log_requested.emit("Local file saved.", "info")

    def _save_remote(
        self,
        editor: CodeEditorWidget,
        session: EditorSession,
        *,
        force: bool = False,
        remote_path: str | None = None,
    ) -> None:
        assert self.manager is not None
        worker = AsyncWorker(
            lambda: self.manager.save_remote_file(
                session,
                editor.text(),
                force=force,
                remote_path=remote_path,
            )
        )
        self._track_worker(worker)
        worker.succeeded.connect(lambda result: self._saved(editor, result))
        worker.failed.connect(lambda result: self._save_failed(editor, session, result))
        worker.start()

    def _saved(self, editor: CodeEditorWidget, result: OperationResult) -> None:
        session = self.sessions.get(editor)
        if session:
            session.dirty = False
            editor.path = session.display_name
        self._set_clean_title(editor)
        self.log_requested.emit(result.message, "info")

    def _save_failed(self, editor: CodeEditorWidget, session: EditorSession, result: OperationResult) -> None:
        if "changed after opening" in result.message.lower() and self.manager is not None:
            box = QMessageBox(self)
            box.setWindowTitle("Remote file changed")
            box.setText("The remote file changed after this editor tab was opened.")
            compare = box.addButton("Review Diff", QMessageBox.ButtonRole.ActionRole)
            overwrite = box.addButton("Overwrite Remote", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() == compare:
                self._review_current_diff()
            elif box.clickedButton() == overwrite:
                self._save_remote(editor, session, force=True)
            return

        if "permission" in result.message.lower():
            resp = QMessageBox.question(
                self,
                "Permission Denied",
                f"Could not write to {session.remote_path}.\n\nDo you want to retry with Sudo elevation?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp == QMessageBox.StandardButton.Yes:
                self._save_remote(editor, session, force=True)
            return

        self._show_error(result)

    def _format_current(self) -> None:
        editor = self.current_editor()
        if editor:
            editor.run_command("format")
            self.log_requested.emit("Formatted document.", "info")

    def _review_current_diff(self) -> None:
        editor = self.current_editor()
        session = self.sessions.get(editor) if editor else None
        if editor is None or session is None:
            return

        local_text = editor.text()
        if session.remote_path and self.manager is not None:
            worker = AsyncWorker(lambda: self.manager.read_remote_text(session))
            self._track_worker(worker)
            worker.succeeded.connect(lambda res: self._show_diff_dialog(session.display_name, local_text, res.data["text"]))
            worker.failed.connect(lambda err: self._show_diff_dialog(session.display_name, local_text, session.local_path.read_text(encoding=session.encoding, errors="replace")))
            worker.start()
        else:
            orig_text = session.local_path.read_text(encoding=session.encoding, errors="replace") if session.local_path.exists() else ""
            self._show_diff_dialog(session.display_name, local_text, orig_text)

    def _show_diff_dialog(self, title: str, modified_text: str, original_text: str) -> None:
        DiffViewerDialog(
            modified_text,
            original_text,
            title=f"Review Diff: {title}",
            parent=self,
        ).exec()

    def _run_current_in_terminal(self) -> None:
        editor = self.current_editor()
        session = self.sessions.get(editor) if editor else None
        if session is None:
            return
        target_path = session.remote_path or str(session.local_path)
        self.run_in_terminal_requested.emit(target_path)
        self.log_requested.emit(f"Launched {target_path} in terminal.", "info")

    def _open_language_selector(self) -> None:
        editor = self.current_editor()
        if not editor:
            return
        dlg = LanguageModeDialog(editor.language(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lang_id, lang_name = dlg.get_selected_language()
            editor.set_language(lang_id)
            self.lang_mode_btn.setText(f"{lang_id.upper()} ▾")
            self.log_requested.emit(f"Switched language mode to {lang_name}.", "info")

    def close_tab(self, index: int) -> None:
        if index < 0 or index >= self.tabs.count():
            return
        editor = self.tabs.tabData(index)
        if isinstance(editor, CodeEditorWidget):
            session = self.sessions.get(editor)
            if session and session.dirty:
                response = QMessageBox.question(self, "Unsaved changes", f"Close {session.display_name} with unsaved changes?")
                if response != QMessageBox.StandardButton.Yes:
                    return
            self.sessions.pop(editor, None)
            self.editor_stack.removeWidget(editor)
            editor.deleteLater()
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.editor_stack.setCurrentWidget(self.empty_placeholder)
            self._clear_hud_and_status()

    def _clear_hud_and_status(self) -> None:
        self.breadcrumb_path.setText("No file open")
        self.permissions_badge.setText("0644 (-rw-r--r--)")
        self.owner_badge.setText("root:root")
        self.size_badge.setText("0 B")
        self.dirty_badge.setText("✓ In Sync")
        self.dirty_badge.setStyleSheet("color: #10b981; font-weight: 600;")
        self.cursor_pos_label.setText("Ln 1, Col 1")
        self.stats_label.setText("0 lines (0 chars)")
        self.sync_status_label.setText("✓ Ready")
        self.sync_status_label.setStyleSheet("color: #10b981; font-weight: 500;")
        self.lang_mode_btn.setText("Plain Text ▾")

    def close_all(self) -> None:
        for index in range(self.tabs.count() - 1, -1, -1):
            self.close_tab(index)

    def _track_worker(self, worker: AsyncWorker) -> None:
        self._workers.append(worker)

    def _show_error(self, result: OperationResult) -> None:
        QMessageBox.critical(self, "Editor Error", result.message)
