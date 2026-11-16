from __future__ import annotations

import os
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.icons import get_icon


class SettingsPanel(QWidget):
    settings_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SettingsPanel")
        self.setStyleSheet("QWidget#SettingsPanel { background: #09090b; }")

        # Controls
        self.theme = QComboBox()
        self.theme.addItems(["System", "Dark", "Light"])
        self.default_local = QLineEdit()
        self.btn_browse_local = QPushButton("Browse")
        self.concurrent_transfers = QSpinBox()
        self.concurrent_transfers.setRange(1, 16)
        self.concurrent_transfers.setValue(3)
        self.backup_before_save = QCheckBox("Automatically create backup snapshot before saving remote files")
        self.backup_before_save.setChecked(True)
        self.confirm_dangerous = QCheckBox("Prompt for confirmation on recursive deletions and remote overwrites")
        self.confirm_dangerous.setChecked(True)
        self.rclone_path = QLineEdit("rclone")
        self.rsync_path = QLineEdit("rsync")
        self.terminal_profile_name = QLineEdit("Default Shell")
        self.terminal_startup_command = QLineEdit()
        self.terminal_default_target = QComboBox()
        self.terminal_default_target.addItem("Active remote connection", "active_remote")
        self.terminal_default_target.addItem("Local shell (PTY)", "local")
        self.terminal_local_shell = QLineEdit()
        placeholder = "powershell.exe, cmd.exe, or pwsh.exe" if os.name == "nt" else "$SHELL, /bin/bash, or /bin/sh"
        self.terminal_local_shell.setPlaceholderText(placeholder)
        self.terminal_font_size = QSpinBox()
        self.terminal_font_size.setRange(8, 40)
        self.terminal_font_size.setValue(13)
        self.terminal_scrollback = QSpinBox()
        self.terminal_scrollback.setRange(500, 50000)
        self.terminal_scrollback.setValue(5000)
        self.local_file_view = QComboBox()
        self.remote_file_view = QComboBox()
        for selector in (self.local_file_view, self.remote_file_view):
            selector.addItem("Details table", "details")
            selector.addItem("Tree view", "tree")

        self._style_controls()

        # Integrated Header
        header = QFrame()
        header.setObjectName("SettingsHeader")
        header.setStyleSheet("""
            QFrame#SettingsHeader {
                background: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
            QFrame#SettingsHeader QLabel {
                background: transparent;
                border: none;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(10)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        h_title = QLabel("Preferences & Workbench Settings")
        h_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f4f4f5;")
        h_sub = QLabel("Configure network concurrency, terminal profiles, editor safety, and keyring integration")
        h_sub.setStyleSheet("font-size: 12px; color: #71717a;")
        header_text.addWidget(h_title)
        header_text.addWidget(h_sub)
        header_layout.addLayout(header_text)
        header_layout.addStretch()

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; border: none; }")

        container = QWidget()
        container.setStyleSheet("background: transparent; border: none;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(16, 16, 16, 16)
        container_layout.setSpacing(16)

        # 1. Appearance & Workspace Card
        card_app = self._build_card("APPEARANCE & WORKSPACE", [
            ("Color Theme", self.theme, "Select between dark Linear aesthetic, system default, or light mode."),
            ("Default Local Path", self._row_with_btn(self.default_local, self.btn_browse_local), "Starting directory for the local pane upon launch."),
            ("Local Pane Layout", self.local_file_view, "Default list presentation for local filesystem."),
            ("Remote Pane Layout", self.remote_file_view, "Default list presentation for remote servers."),
        ])
        container_layout.addWidget(card_app)

        # 2. Transfers & Network Card
        card_trans = self._build_card("TRANSFERS & NETWORK ENGINE", [
            ("Concurrent Transfers", self.concurrent_transfers, "Maximum simultaneous parallel upload/download threads."),
            ("rsync Binary Path", self.rsync_path, "Executable path for accelerated delta synchronizations."),
            ("rclone Binary Path", self.rclone_path, "Executable path for multi-cloud storage operations."),
            ("Safety Snapshots", self.backup_before_save, ""),
            ("Confirmation Prompts", self.confirm_dangerous, ""),
        ])
        container_layout.addWidget(card_trans)

        # 3. Terminal Card
        card_term = self._build_card("EMBEDDED TERMINAL & PTY", [
            ("Profile Name", self.terminal_profile_name, "Label for primary terminal configuration."),
            ("Default Session Target", self.terminal_default_target, "Target environment when creating new terminal tabs."),
            ("Local Shell Executable", self.terminal_local_shell, "Path to local shell binary (leave blank for system $SHELL)."),
            ("Startup Command", self.terminal_startup_command, "Initial script or command executed upon shell launch."),
            ("Font Size", self.terminal_font_size, "Monospace font size in pixels (WebGL xterm renderer)."),
            ("Scrollback Buffer", self.terminal_scrollback, "Total lines preserved in terminal scroll memory."),
        ])
        container_layout.addWidget(card_term)
        container_layout.addStretch()

        scroll.setWidget(container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(scroll, 1)

        # Wiring
        self.btn_browse_local.clicked.connect(self._browse_local_path)
        self.theme.currentIndexChanged.connect(self._emit_settings)
        self.default_local.editingFinished.connect(self._emit_settings)
        self.concurrent_transfers.valueChanged.connect(self._emit_settings)
        self.backup_before_save.toggled.connect(self._emit_settings)
        self.confirm_dangerous.toggled.connect(self._emit_settings)
        self.rsync_path.editingFinished.connect(self._emit_settings)
        self.rclone_path.editingFinished.connect(self._emit_settings)
        self.terminal_profile_name.editingFinished.connect(self._emit_settings)
        self.terminal_startup_command.editingFinished.connect(self._emit_settings)
        self.terminal_default_target.currentIndexChanged.connect(self._emit_settings)
        self.terminal_local_shell.editingFinished.connect(self._emit_settings)
        self.terminal_font_size.valueChanged.connect(self._emit_settings)
        self.terminal_scrollback.valueChanged.connect(self._emit_settings)
        self.local_file_view.currentIndexChanged.connect(self._emit_settings)
        self.remote_file_view.currentIndexChanged.connect(self._emit_settings)

    def _build_card(self, title: str, rows: list[tuple[str, QWidget, str]]) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingsCard")
        card.setStyleSheet("""
            QFrame#SettingsCard {
                background: #121215;
                border: 1px solid #1e1e24;
                border-radius: 8px;
            }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(14, 12, 14, 12)
        c_layout.setSpacing(10)

        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px; margin-bottom: 2px;")
        c_layout.addWidget(lbl)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        for label_text, widget, hint in rows:
            lbl_w = QLabel(label_text)
            lbl_w.setStyleSheet("color: #d4d4d8; font-size: 13px; font-weight: 500;")
            if hint:
                col = QVBoxLayout()
                col.setSpacing(2)
                col.addWidget(widget)
                h_lbl = QLabel(hint)
                h_lbl.setStyleSheet("color: #71717a; font-size: 11px;")
                col.addWidget(h_lbl)
                form.addRow(lbl_w, col)
            else:
                form.addRow(lbl_w, widget)

        c_layout.addLayout(form)
        return card

    def _row_with_btn(self, line_edit: QLineEdit, button: QPushButton) -> QWidget:
        box = QWidget()
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(8)
        box_layout.addWidget(line_edit, 1)
        box_layout.addWidget(button)
        return box

    def _style_controls(self) -> None:
        line_edit_css = "QLineEdit { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 12px; } QLineEdit:focus { border-color: #6366f1; }"
        combo_css = "QComboBox { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 12px; min-width: 140px; }"
        spin_css = "QSpinBox { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 12px; min-width: 100px; }"
        btn_css = "QPushButton { background: #18181b; color: #e4e4e7; border: 1px solid #27272a; border-radius: 6px; height: 30px; padding: 0 12px; } QPushButton:hover { background: #27272a; }"

        for w in [self.default_local, self.rclone_path, self.rsync_path, self.terminal_profile_name, self.terminal_startup_command, self.terminal_local_shell]:
            w.setStyleSheet(line_edit_css)
        for w in [self.theme, self.terminal_default_target, self.local_file_view, self.remote_file_view]:
            w.setStyleSheet(combo_css)
        for w in [self.concurrent_transfers, self.terminal_font_size, self.terminal_scrollback]:
            w.setStyleSheet(spin_css)
        self.btn_browse_local.setStyleSheet(btn_css)

    def _browse_local_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose default local folder", self.default_local.text() or str(Path.home()))
        if path:
            self.default_local.setText(path)
            self._emit_settings()

    def _emit_settings(self) -> None:
        self.settings_changed.emit(self.current_settings())

    def apply_settings(self, settings: dict) -> None:
        self.concurrent_transfers.setValue(int(settings.get("transfer.max_concurrent", 3)))
        terminal = settings.get("terminal", {})
        tools = settings.get("tools", {})
        self.rsync_path.setText(str(tools.get("rsync_path", "rsync")))
        self.rclone_path.setText(str(tools.get("rclone_path", "rclone")))
        profiles = terminal.get("profiles") or [{"name": "Default Shell", "startup_command": ""}]
        profile = profiles[0]
        self.terminal_profile_name.setText(profile.get("name", "Default Shell"))
        self.terminal_startup_command.setText(profile.get("startup_command", ""))
        target = terminal.get("default_new_target", "active_remote")
        target_index = self.terminal_default_target.findData(target)
        self.terminal_default_target.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.terminal_local_shell.setText(terminal.get("local_shell_path", ""))
        self.terminal_font_size.setValue(int(terminal.get("font_size", 13)))
        self.terminal_scrollback.setValue(int(terminal.get("scrollback", 5000)))
        browser = settings.get("file_browser", {})
        for selector, key in ((self.local_file_view, "local_view"), (self.remote_file_view, "remote_view")):
            index = selector.findData(browser.get(key, "details"))
            selector.setCurrentIndex(index if index >= 0 else 0)

    def current_settings(self) -> dict:
        return {
            "transfer.max_concurrent": self.concurrent_transfers.value(),
            "terminal": {
                "profiles": [
                    {
                        "name": self.terminal_profile_name.text().strip() or "Default Shell",
                        "startup_command": self.terminal_startup_command.text().strip(),
                        "cwd_mode": "current_remote_path",
                        "theme": "dark",
                    }
                ],
                "default_profile": self.terminal_profile_name.text().strip() or "Default Shell",
                "font_size": self.terminal_font_size.value(),
                "scrollback": self.terminal_scrollback.value(),
                "default_new_target": self.terminal_default_target.currentData() or "active_remote",
                "local_shell_path": self.terminal_local_shell.text().strip(),
                "local_cwd_mode": "current_local_path",
            },
            "tools": {
                "rsync_path": self.rsync_path.text().strip() or "rsync",
                "rclone_path": self.rclone_path.text().strip() or "rclone",
            },
            "file_browser": {
                "local_view": self.local_file_view.currentData() or "details",
                "remote_view": self.remote_file_view.currentData() or "details",
            },
        }
