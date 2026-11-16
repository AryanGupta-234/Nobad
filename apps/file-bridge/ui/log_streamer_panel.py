from __future__ import annotations

import asyncio
import os
import shlex
from typing import Any

from shiboken6 import isValid

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.log_streamer import (
    DEFAULT_LOG_PRESETS,
    LogEntry,
    LogSourceType,
    LogStreamConfig,
    LogStreamManager,
    LogStreamStatus,
)
from core.result import OperationResult
from ui.async_worker import AsyncRuntime
from ui.icons import get_icon
from ui.log_stream_pane import LogStreamPane


class LogStreamerNoConnectionDialog(QDialog):
    """
    Polished Raycast/Linear dark mode dialog alerting the user when an action
    requires an active SSH connection.
    """

    def __init__(self, action_name: str = "Live Log Streaming", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogStreamerNoConnectionDialog")
        self.setWindowTitle("Server Not Connected — NOBAD File Bridge")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedWidth(520)
        self.setStyleSheet("""
            QDialog#LogStreamerNoConnectionDialog {
                background-color: #13131c;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        # 1. Header with Warning Badge
        hdr = QHBoxLayout()
        hdr.setSpacing(12)

        icon_box = QLabel()
        icon_box.setFixedSize(38, 38)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setStyleSheet(
            "background-color: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 8px;"
        )
        icon_box.setPixmap(get_icon("alert", color="#f59e0b", size=20).pixmap(20, 20))
        hdr.addWidget(icon_box)

        title_l = QVBoxLayout()
        title_l.setSpacing(2)
        heading = QLabel("Server Not Connected")
        heading.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff; border: none; background: transparent;")
        title_l.addWidget(heading)

        subheading = QLabel("Active SSH session required for real-time log streaming")
        subheading.setStyleSheet("font-size: 11px; color: #94a3b8; border: none; background: transparent;")
        title_l.addWidget(subheading)
        hdr.addLayout(title_l)
        hdr.addStretch(1)
        layout.addLayout(hdr)

        # 2. Main Message Box
        msg_frame = QFrame()
        msg_frame.setObjectName("MsgFrame")
        msg_frame.setStyleSheet("""
            QFrame#MsgFrame {
                background-color: #171724;
                border: 1px solid #252536;
                border-radius: 8px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        msg_l = QVBoxLayout(msg_frame)
        msg_l.setContentsMargins(16, 14, 16, 14)
        msg_l.setSpacing(10)

        msg_lbl = QLabel(
            f"Cannot initiate <b>{action_name}</b> because no remote server is currently connected.<br><br>"
            "Please connect to an active SSH or SFTP host to tail remote logs in real-time."
        )
        msg_lbl.setWordWrap(True)
        msg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg_lbl.setStyleSheet("font-size: 12px; color: #e2e8f0; line-height: 1.45; border: none; background: transparent;")
        msg_l.addWidget(msg_lbl)

        tip_lbl = QLabel("Tip: You can prepare log stream configurations now; streaming will start automatically once an SSH connection is established.")
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet("font-size: 11px; color: #38bdf8; border: none; background: transparent; padding-top: 2px;")
        msg_l.addWidget(tip_lbl)
        layout.addWidget(msg_frame)

        # 3. Actions Row
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)

        cancel_btn = QPushButton("Close")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e1e2c;
                border: 1px solid #2e2e42;
                border-radius: 6px;
                color: #cbd5e1;
                padding: 6px 16px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2b2b40;
                color: #ffffff;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)

        connect_btn = QPushButton("Connect to Server")
        connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                padding: 6px 18px;
                font-weight: 700;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
        """)
        connect_btn.clicked.connect(self.accept)
        actions.addWidget(connect_btn)

        layout.addLayout(actions)


class NewLogStreamDialog(QDialog):
    """
    Modal dialog to attach a new remote live log tail stream (tail -F or journalctl)
    with preset quick picks, SFTP path browse, and command preview.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Attach New Live Log Stream — NOBAD File Bridge")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedWidth(640)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #121217;
                border: 1px solid #272738;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet("background-color: #181824; border-top-left-radius: 11px; border-top-right-radius: 11px; border-bottom: 1px solid #232334;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)
        h_layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setPixmap(get_icon("logs", color="#10b981", size=22).pixmap(22, 22))
        h_layout.addWidget(icon_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = QLabel("Attach New Live Log Stream")
        title_lbl.setStyleSheet("color: #f4f4f5; font-size: 13px; font-weight: bold;")
        sub_lbl = QLabel("Tail remote server logs in real time (`tail -F`) or stream systemd journal units")
        sub_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)
        h_layout.addLayout(title_box)

        h_layout.addStretch()
        close_x = QPushButton("✕")
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setFixedSize(24, 24)
        close_x.setStyleSheet("background: transparent; color: #71717a; border: none; font-size: 13px;")
        close_x.clicked.connect(self.reject)
        h_layout.addWidget(close_x)

        layout.addWidget(header)

        # Body
        body = QWidget()
        b_layout = QVBoxLayout(body)
        b_layout.setContentsMargins(20, 16, 20, 16)
        b_layout.setSpacing(14)

        # Presets Grid
        preset_lbl = QLabel("COMMON LOG PRESETS")
        preset_lbl.setStyleSheet("color: #a1a1aa; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
        b_layout.addWidget(preset_lbl)

        p_grid = QGridLayout()
        p_grid.setSpacing(8)

        self.preset_buttons: list[QPushButton] = []
        for i, preset in enumerate(DEFAULT_LOG_PRESETS):
            btn = QPushButton(f"{preset['name']}\n{preset['target_path']}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(44)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #14141e;
                    color: #e4e4e7;
                    border: 1px solid #232334;
                    border-radius: 6px;
                    text-align: left;
                    padding-left: 10px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background-color: #1c1c2a;
                    border: 1px solid #4f46e5;
                }
            """)
            btn.clicked.connect(lambda _, p=preset: self._apply_preset(p))
            self.preset_buttons.append(btn)
            p_grid.addWidget(btn, i // 4, i % 4)

        b_layout.addLayout(p_grid)

        # Form Fields
        fields_row = QHBoxLayout()
        fields_row.setSpacing(12)

        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        name_lbl = QLabel("Stream Display Name")
        name_lbl.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        self.name_input = QLineEdit("Nginx Access")
        self.name_input.setFixedHeight(28)
        self.name_input.setStyleSheet("background-color: #14141e; color: #f4f4f5; border: 1px solid #232334; border-radius: 6px; padding: 0 8px; font-family: 'JetBrains Mono'; font-size: 11px;")
        name_box.addWidget(name_lbl)
        name_box.addWidget(self.name_input)
        fields_row.addLayout(name_box)

        type_box = QVBoxLayout()
        type_box.setSpacing(4)
        type_lbl = QLabel("Source Type")
        type_lbl.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        self.type_combo = QComboBox()
        self.type_combo.setFixedHeight(28)
        self.type_combo.addItem("Remote Log File (tail -F)", "file")
        self.type_combo.addItem("Systemd Journal Unit (journalctl -u)", "journal")
        self.type_combo.setStyleSheet("background-color: #14141e; color: #f4f4f5; border: 1px solid #232334; border-radius: 6px; padding: 0 8px; font-size: 11px;")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_box.addWidget(type_lbl)
        type_box.addWidget(self.type_combo)
        fields_row.addLayout(type_box)

        b_layout.addLayout(fields_row)

        # Path input
        self.path_box = QVBoxLayout()
        self.path_box.setSpacing(4)
        self.path_lbl = QLabel("Remote File Path")
        self.path_lbl.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        path_h = QHBoxLayout()
        self.path_input = QLineEdit("/var/log/nginx/access.log")
        self.path_input.setFixedHeight(28)
        self.path_input.setStyleSheet("background-color: #14141e; color: #f4f4f5; border: 1px solid #232334; border-radius: 6px; padding: 0 8px; font-family: 'JetBrains Mono'; font-size: 11px;")
        self.path_input.textChanged.connect(self._update_preview)
        path_h.addWidget(self.path_input, 1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.setFixedHeight(28)
        self.browse_btn.setStyleSheet("background-color: #1e1e2c; color: #e4e4e7; border: 1px solid #2a2a3e; border-radius: 6px; padding: 0 10px; font-size: 11px;")
        path_h.addWidget(self.browse_btn)

        self.path_box.addWidget(self.path_lbl)
        self.path_box.addLayout(path_h)
        b_layout.addLayout(self.path_box)

        # Options
        opts_row = QHBoxLayout()
        opts_row.setSpacing(16)

        bootstrap_box = QVBoxLayout()
        bootstrap_box.setSpacing(4)
        boot_lbl = QLabel("Initial Bootstrap Lines")
        boot_lbl.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        self.bootstrap_combo = QComboBox()
        self.bootstrap_combo.setFixedHeight(28)
        self.bootstrap_combo.addItem("50 recent lines", 50)
        self.bootstrap_combo.addItem("150 recent lines (Default)", 150)
        self.bootstrap_combo.addItem("300 recent lines", 300)
        self.bootstrap_combo.addItem("1,000 lines (Heavy)", 1000)
        self.bootstrap_combo.setCurrentIndex(1)
        self.bootstrap_combo.setStyleSheet("background-color: #14141e; color: #f4f4f5; border: 1px solid #232334; border-radius: 6px; padding: 0 8px; font-size: 11px;")
        self.bootstrap_combo.currentIndexChanged.connect(self._update_preview)
        bootstrap_box.addWidget(boot_lbl)
        bootstrap_box.addWidget(self.bootstrap_combo)
        opts_row.addLayout(bootstrap_box)

        check_box = QVBoxLayout()
        check_box.setSpacing(6)
        check_box.addSpacing(16)

        check_style = """
            QCheckBox {
                color: #cbd5e1;
                font-size: 11px;
                font-weight: 500;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #3b3b4f;
                border-radius: 4px;
                background-color: #171724;
            }
            QCheckBox::indicator:hover {
                border-color: #6366f1;
                background-color: #1e1e2f;
            }
            QCheckBox::indicator:checked {
                border-color: #6366f1;
                background-color: #6366f1;
            }
        """
        self.follow_check = QCheckBox("Follow across log rotations (tail -F)")
        self.follow_check.setChecked(True)
        self.follow_check.setStyleSheet(check_style)
        self.follow_check.toggled.connect(self._update_preview)
        check_box.addWidget(self.follow_check)

        self.sudo_check = QCheckBox("Use sudo escalation (for restricted logs)")
        self.sudo_check.setChecked(False)
        self.sudo_check.setStyleSheet(check_style)
        self.sudo_check.toggled.connect(self._update_preview)
        check_box.addWidget(self.sudo_check)

        opts_row.addLayout(check_box)
        b_layout.addLayout(opts_row)

        # Command Preview Box
        cmd_box = QVBoxLayout()
        cmd_box.setSpacing(4)
        cmd_lbl = QLabel("EXECUTED REMOTE COMMAND PREVIEW")
        cmd_lbl.setStyleSheet("color: #71717a; font-size: 10px; font-weight: bold;")
        self.preview_lbl = QLabel()
        self.preview_lbl.setStyleSheet("""
            background-color: #0c0c11;
            color: #10b981;
            border: 1px solid #1f1f2e;
            border-radius: 6px;
            padding: 8px 12px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
        """)
        cmd_box.addWidget(cmd_lbl)
        cmd_box.addWidget(self.preview_lbl)
        b_layout.addLayout(cmd_box)

        layout.addWidget(body)

        # Footer
        footer = QFrame()
        footer.setFixedHeight(50)
        footer.setStyleSheet("background-color: #14141e; border-bottom-left-radius: 11px; border-bottom-right-radius: 11px; border-top: 1px solid #1f1f2e;")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(16, 0, 16, 0)
        f_layout.setSpacing(10)

        f_note = QLabel("Non-blocking AsyncSSH channel")
        f_note.setStyleSheet("color: #71717a; font-size: 11px; font-family: 'JetBrains Mono', monospace;")
        f_layout.addWidget(f_note)

        f_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet("background-color: #1e1e2c; color: #e4e4e7; border: 1px solid #2a2a3e; border-radius: 6px; padding: 0 14px; font-size: 11px;")
        cancel_btn.clicked.connect(self.reject)
        f_layout.addWidget(cancel_btn)

        self.start_btn = QPushButton("Start Live Stream")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setFixedHeight(30)
        self.start_btn.setStyleSheet("background-color: #059669; color: #ffffff; border: 1px solid #10b981; border-radius: 6px; padding: 0 16px; font-size: 11px; font-weight: bold;")
        self.start_btn.clicked.connect(self.accept)
        f_layout.addWidget(self.start_btn)

        layout.addWidget(footer)

        self._update_preview()

    def _apply_preset(self, preset: dict[str, Any]) -> None:
        self.name_input.setText(preset["name"])
        source_type = preset.get("source_type", "file")
        idx = 0 if source_type == "file" else 1
        self.type_combo.setCurrentIndex(idx)
        self.path_input.setText(preset.get("target_path", ""))
        self.follow_check.setChecked(preset.get("follow_rotations", True))
        self.sudo_check.setChecked(preset.get("use_sudo", False))
        self._update_preview()

    def _on_type_changed(self) -> None:
        is_file = self.type_combo.currentData() == "file"
        self.path_lbl.setText("Remote File Path" if is_file else "Systemd Service Unit Name")
        self.browse_btn.setVisible(is_file)
        self.follow_check.setVisible(is_file)
        self._update_preview()

    def _update_preview(self) -> None:
        is_file = self.type_combo.currentData() == "file"
        sudo_str = "sudo " if self.sudo_check.isChecked() else ""
        boot_lines = self.bootstrap_combo.currentData() or 150
        target = self.path_input.text().strip() or ("/var/log/syslog" if is_file else "nginx.service")

        if is_file:
            follow = "-F" if self.follow_check.isChecked() else "-f"
            cmd = f"{sudo_str}tail {follow} -n {boot_lines} {target}"
        else:
            cmd = f"{sudo_str}journalctl -u {target} -f -n {boot_lines} -o short-iso"
        self.preview_lbl.setText(cmd)

    def get_config(self) -> LogStreamConfig:
        is_file = self.type_combo.currentData() == "file"
        return LogStreamConfig(
            name=self.name_input.text().strip() or "Custom Stream",
            source_type=LogSourceType.FILE if is_file else LogSourceType.JOURNAL,
            target_path=self.path_input.text().strip() if is_file else "",
            unit_name=self.path_input.text().strip() if not is_file else "",
            bootstrap_lines=self.bootstrap_combo.currentData() or 150,
            follow_rotations=self.follow_check.isChecked(),
            use_sudo=self.sudo_check.isChecked(),
        )


class LogStreamerPanel(QWidget):
    """
    Central workbench panel for monitoring production logs in real time over SSH.
    Supports single view, 2-column split, 2-row stacked, and 4-pane quad grid layouts,
    presets, and sticky auto-scroll locking.
    """

    connect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection: Any = None
        self._profile: Any = None
        self._manager = LogStreamManager()
        self._panes: dict[str, LogStreamPane] = {}
        self._current_layout = "split"  # "single", "split", "stacked", "quad"
        self._sync_scroll = False
        self._global_paused = False

        self._init_ui()
        self.apply_preset("nginx-dual", notify_if_disconnected=False)

        # Telemetry refresh timer
        self._kpi_timer = QTimer(self)
        self._kpi_timer.setInterval(1000)
        self._kpi_timer.timeout.connect(self._refresh_kpis)
        self._kpi_timer.start()

        # Start in empty/disconnected state (index 0)
        self.stack.setCurrentIndex(0)

    def _init_ui(self) -> None:
        self.setObjectName("LogStreamerPanel")
        self.setStyleSheet("""
            QWidget#LogStreamerPanel {
                background-color: #09090b;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Stack to switch between Live Streamer Dashboard and Disconnected Empty State
        self.stack = QStackedWidget(self)
        main_layout.addWidget(self.stack)

        self._build_empty_view()
        self._build_streamer_view()

    def _build_empty_view(self) -> None:
        empty = QWidget()
        empty.setObjectName("EmptyLogStreamerView")
        empty.setStyleSheet("background: transparent;")
        l = QVBoxLayout(empty)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setSpacing(0)

        card = QFrame()
        card.setObjectName("EmptyStateCard")
        card.setFixedWidth(520)
        card.setStyleSheet("""
            QFrame#EmptyStateCard {
                background-color: #15151c;
                border: 1px solid #262634;
                border-radius: 16px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(36, 36, 36, 36)
        card_l.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setObjectName("EmptyIcon")
        icon_lbl.setFixedSize(52, 52)
        pix = get_icon("logs", color="#10b981", size=30).pixmap(30, 30)
        icon_lbl.setPixmap(pix)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("""
            QLabel#EmptyIcon {
                background-color: rgba(16, 185, 129, 0.15);
                border: 1px solid rgba(16, 185, 129, 0.35);
                border-radius: 14px;
            }
        """)
        card_l.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Live Multi-Log Streamer")
        title.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #ffffff; background: transparent; border: none; padding: 0;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_l.addWidget(title)

        desc = QLabel(
            "Connect to an SSH host to stream live remote server logs in real time (`tail -F`), "
            "inspect systemd journal units, and compare multi-pane logs side-by-side agentlessly "
            "without installing anything on the remote host."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(
            "font-size: 13px; color: #94a3b8; background: transparent; border: none; padding: 0 16px; line-height: 1.4;"
        )
        card_l.addWidget(desc)

        card_l.addSpacing(6)

        connect_btn = QPushButton("Go to Connections")
        connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        connect_btn.setFixedSize(180, 38)
        connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
        """)
        connect_btn.clicked.connect(self.connect_requested.emit)
        card_l.addWidget(connect_btn, 0, Qt.AlignmentFlag.AlignCenter)

        l.addWidget(card)
        self.stack.addWidget(empty)

    def _build_streamer_view(self) -> None:
        view = QWidget()
        view.setObjectName("StreamerContentView")
        view.setStyleSheet("background: transparent;")
        v_layout = QVBoxLayout(view)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)

        # 1. Top Header & KPI Strip
        header_widget = self._build_header_section()
        v_layout.addWidget(header_widget)

        # 2. Main Multi-Pane Splitter Canvas
        self.canvas_area = QWidget()
        self.canvas_area.setStyleSheet("background-color: #09090b;")
        self.canvas_layout = QVBoxLayout(self.canvas_area)
        self.canvas_layout.setContentsMargins(8, 8, 8, 8)
        self.canvas_layout.setSpacing(8)

        # Default splitter container
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1f1f2e;
                width: 4px;
                height: 4px;
            }
            QSplitter::handle:hover {
                background-color: #4f46e5;
            }
        """)
        self.canvas_layout.addWidget(self.main_splitter, 1)

        v_layout.addWidget(self.canvas_area, 1)
        self.stack.addWidget(view)

    def _build_header_section(self) -> QWidget:
        container = QFrame()
        container.setObjectName("LogStreamerHeader")
        container.setStyleSheet("""
            QFrame#LogStreamerHeader {
                background-color: #121217;
                border-bottom: 1px solid #1f1f2e;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(18, 14, 18, 12)
        c_layout.setSpacing(10)

        # Row 1: Title & Server Context + Action Buttons
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon("logs", color="#10b981", size=24).pixmap(24, 24))
        top_row.addWidget(icon_lbl)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)

        title_h = QHBoxLayout()
        title_h.setSpacing(8)
        title_text = QLabel("Live Multi-Log Streamer")
        title_text.setStyleSheet("color: #f4f4f5; font-size: 14px; font-weight: bold; font-family: Inter, system-ui;")
        title_h.addWidget(title_text)

        self.active_badge = QLabel("0 Streams Live (0.0 l/s)")
        self.active_badge.setStyleSheet("""
            background-color: rgba(16, 185, 129, 0.12);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.25);
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        """)
        title_h.addWidget(self.active_badge)

        self.host_badge = QLabel("Disconnected")
        self.host_badge.setStyleSheet("""
            background-color: #161622;
            color: #a1a1aa;
            border: 1px solid #232334;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 10px;
            font-family: 'JetBrains Mono', monospace;
        """)
        title_h.addWidget(self.host_badge)
        title_h.addStretch()

        subtitle = QLabel("Real-time log tailing (`tail -F`), regex filtering, sticky auto-scroll, and multi-pane split comparisons")
        subtitle.setStyleSheet("color: #71717a; font-size: 11px;")

        title_vbox.addLayout(title_h)
        title_vbox.addWidget(subtitle)
        top_row.addLayout(title_vbox, 1)

        # Layout Mode Selector Group
        layout_box = QFrame()
        layout_box.setStyleSheet("background-color: #161622; border: 1px solid #232334; border-radius: 6px;")
        lb_layout = QHBoxLayout(layout_box)
        lb_layout.setContentsMargins(2, 2, 2, 2)
        lb_layout.setSpacing(2)

        self.btn_single = self._create_layout_button("Single", "single")
        self.btn_split = self._create_layout_button("2 Columns", "split", active=True)
        self.btn_stacked = self._create_layout_button("Stacked", "stacked")
        self.btn_quad = self._create_layout_button("Quad", "quad")

        lb_layout.addWidget(self.btn_single)
        lb_layout.addWidget(self.btn_split)
        lb_layout.addWidget(self.btn_stacked)
        lb_layout.addWidget(self.btn_quad)
        top_row.addWidget(layout_box)

        # Add Stream Button on Row 1
        add_btn = QPushButton("+ Add Stream")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setFixedHeight(26)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #4f46e5;
                color: #ffffff;
                border: 1px solid #6366f1;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4338ca;
            }
        """)
        add_btn.clicked.connect(self.open_new_stream_dialog)
        top_row.addWidget(add_btn)

        c_layout.addLayout(top_row)

        # Row 2: Popular Presets Strip (Left) + Stream Controls (Right)
        presets_row = QHBoxLayout()
        presets_row.setContentsMargins(0, 0, 0, 0)
        presets_row.setSpacing(6)

        preset_tag = QLabel("⚡ PRESETS:")
        preset_tag.setStyleSheet("color: #a1a1aa; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
        presets_row.addWidget(preset_tag)

        self.preset_btns: dict[str, QPushButton] = {}
        presets_config = [
            ("nginx-dual", "Nginx Dual"),
            ("security", "Auth & Syslog"),
            ("web-db", "Web + DB"),
            ("apache", "Apache Dual"),
            ("docker", "Docker"),
        ]

        for p_key, p_label in presets_config:
            p_btn = QPushButton(p_label)
            p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            p_btn.setFixedHeight(22)
            p_btn.setStyleSheet(self._preset_btn_style(active=(p_key == "nginx-dual")))
            p_btn.clicked.connect(lambda _, k=p_key: self.apply_preset(k, notify_if_disconnected=True))
            self.preset_btns[p_key] = p_btn
            presets_row.addWidget(p_btn)

        custom_btn = QPushButton("+ Custom...")
        custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        custom_btn.setFixedHeight(22)
        custom_btn.setStyleSheet(self._preset_btn_style(active=False))
        custom_btn.clicked.connect(self.open_new_stream_dialog)
        presets_row.addWidget(custom_btn)

        presets_row.addStretch()

        # Sync Scroll Checkbox
        self.sync_scroll_check = QCheckBox("Sync Scroll")
        self.sync_scroll_check.setChecked(False)
        self.sync_scroll_check.setToolTip("Synchronize scroll position across all visible panes")
        self.sync_scroll_check.setStyleSheet("""
            QCheckBox {
                color: #d4d4d8;
                font-size: 11px;
                font-family: 'JetBrains Mono', monospace;
                background-color: #161622;
                border: 1px solid #232334;
                border-radius: 6px;
                padding: 2px 8px;
                spacing: 6px;
                height: 22px;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
                border: 1px solid #3b3b4f;
                border-radius: 3px;
                background-color: #171724;
            }
            QCheckBox::indicator:hover {
                border-color: #6366f1;
                background-color: #1e1e2f;
            }
            QCheckBox::indicator:checked {
                border-color: #6366f1;
                background-color: #6366f1;
            }
        """)
        self.sync_scroll_check.toggled.connect(self._toggle_sync_scroll)
        presets_row.addWidget(self.sync_scroll_check)

        # Global Pause/Resume Button
        self.global_pause_btn = QPushButton("❚❚ Pause All")
        self.global_pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_pause_btn.setFixedHeight(22)
        self.global_pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #161622;
                color: #e4e4e7;
                border: 1px solid #232334;
                border-radius: 6px;
                padding: 0 8px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #232334;
            }
        """)
        self.global_pause_btn.clicked.connect(self.toggle_global_pause)
        presets_row.addWidget(self.global_pause_btn)

        # Global Clear Button
        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_all_btn.setFixedHeight(22)
        clear_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #161622;
                color: #a1a1aa;
                border: 1px solid #232334;
                border-radius: 6px;
                padding: 0 8px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        clear_all_btn.clicked.connect(self.clear_all_streams)
        presets_row.addWidget(clear_all_btn)

        c_layout.addLayout(presets_row)

        # Row 3: 4 KPI Summary Cards
        kpi_grid = QHBoxLayout()
        kpi_grid.setSpacing(10)

        self.card_streams = self._build_kpi_card("ACTIVE STREAMS", "0 Streams Live", "0 / 4 Slots", "0% Active")
        self.card_velocity = self._build_kpi_card("STREAMING VELOCITY", "0.0 lines/s", "Real-time log rate", "Live Wave")
        self.card_buffer = self._build_kpi_card("RING BUFFER VOLUME", "0 lines", "RAM: 0.0 MB", "10k Limit")
        self.card_alerts = self._build_kpi_card("ERROR / WARN ALERTS", "0 Errors • 0 Warns", "Regex monitored", "Live Monitored", val_color="#f43f5e")

        kpi_grid.addWidget(self.card_streams)
        kpi_grid.addWidget(self.card_velocity)
        kpi_grid.addWidget(self.card_buffer)
        kpi_grid.addWidget(self.card_alerts)

        c_layout.addLayout(kpi_grid)

        return container

    def _create_layout_button(self, label: str, mode: str, active: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(24)
        btn.setProperty("mode", mode)
        self._update_layout_btn_style(btn, active)
        btn.clicked.connect(lambda: self.set_layout_mode(mode))
        return btn

    def _update_layout_btn_style(self, btn: QPushButton, active: bool) -> None:
        if active:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #272738;
                    color: #ffffff;
                    border: 1px solid #3b3b4f;
                    border-radius: 4px;
                    padding: 0 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #a1a1aa;
                    border: none;
                    border-radius: 4px;
                    padding: 0 8px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    color: #ffffff;
                }
            """)

    def _preset_btn_style(self, active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background-color: rgba(99, 102, 241, 0.15);
                    color: #c7d2fe;
                    border: 1px solid rgba(99, 102, 241, 0.4);
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 10.5px;
                    font-weight: 600;
                }
            """
        return """
            QPushButton {
                background-color: #14141e;
                color: #a1a1aa;
                border: 1px solid #232334;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 10.5px;
            }
            QPushButton:hover {
                background-color: #1c1c2a;
                color: #e4e4e7;
            }
        """

    def _build_kpi_card(self, title: str, val: str, sub: str, tag: str, val_color: str = "#f4f4f5") -> QFrame:
        card = QFrame()
        card.setObjectName("KpiCard")
        card.setFixedHeight(68)
        card.setStyleSheet("""
            QFrame#KpiCard {
                background-color: #14141e;
                border: 1px solid #1f1f2e;
                border-radius: 8px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        top_h = QHBoxLayout()
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("color: #71717a; font-size: 9.5px; font-weight: bold; letter-spacing: 0.5px; border: none; background: transparent;")
        tag_lbl = QLabel(tag)
        tag_lbl.setStyleSheet("background-color: rgba(99, 102, 241, 0.1); color: #818cf8; border: none; border-radius: 3px; padding: 1px 5px; font-size: 9px; font-family: 'JetBrains Mono';")
        top_h.addWidget(t_lbl)
        top_h.addStretch()
        top_h.addWidget(tag_lbl)
        layout.addLayout(top_h)

        val_lbl = QLabel(val)
        val_lbl.setObjectName("val")
        val_lbl.setStyleSheet(f"color: {val_color}; font-size: 16px; font-weight: bold; font-family: 'JetBrains Mono', monospace; border: none; background: transparent;")
        layout.addWidget(val_lbl)

        sub_lbl = QLabel(sub)
        sub_lbl.setObjectName("sub")
        sub_lbl.setStyleSheet("color: #71717a; font-size: 10px; font-family: 'JetBrains Mono', monospace; border: none; background: transparent;")
        layout.addWidget(sub_lbl)

        return card

    def set_connection(self, connection: Any, profile: Any = None) -> None:
        """Handle server connect/disconnect."""
        self._connection = connection
        self._profile = profile

        if connection is None:
            self.host_badge.setText("Disconnected")
            self.active_badge.setText("0 Streams Live (0.0 l/s)")
            AsyncRuntime.instance().submit(self._manager.stop_all_streams())
            for pane in self._panes.values():
                pane.set_status(LogStreamStatus.STOPPED)
            self.stack.setCurrentIndex(0)
            return

        self.stack.setCurrentIndex(1)
        host_str = getattr(profile, "host", "Remote Server")
        user_str = getattr(profile, "username", "root")
        self.host_badge.setText(f"Host: {host_str} ({user_str})")

        # Auto-start Nginx Dual preset on initial connect
        self.apply_preset("nginx-dual")

    def set_layout_mode(self, mode: str) -> None:
        """Switch between single, split (2 columns), stacked (2 rows), and quad (4 panes)."""
        self._current_layout = mode
        self._update_layout_btn_style(self.btn_single, mode == "single")
        self._update_layout_btn_style(self.btn_split, mode == "split")
        self._update_layout_btn_style(self.btn_stacked, mode == "stacked")
        self._update_layout_btn_style(self.btn_quad, mode == "quad")

        # Re-arrange splitter
        self._rebuild_splitter()

    def _rebuild_splitter(self) -> None:
        # 1. Safely reparent all active panes back to self before clearing splitter containers
        for p in self._panes.values():
            if isValid(p):
                p.setParent(self)
                p.hide()

        # 2. Clear lingering intermediate splitters from main_splitter
        while self.main_splitter.count():
            widget = self.main_splitter.widget(0)
            widget.setParent(None)
            widget.deleteLater()

        panes_list = [p for p in self._panes.values() if isValid(p)]
        if not panes_list:
            return

        if self._current_layout == "single":
            self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
            self.main_splitter.addWidget(panes_list[0])
            panes_list[0].show()
            for p in panes_list[1:]:
                p.hide()

        elif self._current_layout == "split":
            self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
            for p in panes_list[:2]:
                self.main_splitter.addWidget(p)
                p.show()
            for p in panes_list[2:]:
                p.hide()
            self.main_splitter.setSizes([500, 500])

        elif self._current_layout == "stacked":
            self.main_splitter.setOrientation(Qt.Orientation.Vertical)
            for p in panes_list[:2]:
                self.main_splitter.addWidget(p)
                p.show()
            for p in panes_list[2:]:
                p.hide()
            self.main_splitter.setSizes([300, 300])

        elif self._current_layout == "quad":
            self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
            left_v = QSplitter(Qt.Orientation.Vertical, self.main_splitter)
            right_v = QSplitter(Qt.Orientation.Vertical, self.main_splitter)
            left_v.setStyleSheet(self.main_splitter.styleSheet())
            right_v.setStyleSheet(self.main_splitter.styleSheet())

            if len(panes_list) > 0:
                left_v.addWidget(panes_list[0])
                panes_list[0].show()
            if len(panes_list) > 1:
                left_v.addWidget(panes_list[1])
                panes_list[1].show()
            if len(panes_list) > 2:
                right_v.addWidget(panes_list[2])
                panes_list[2].show()
            if len(panes_list) > 3:
                right_v.addWidget(panes_list[3])
                panes_list[3].show()

            self.main_splitter.addWidget(left_v)
            self.main_splitter.addWidget(right_v)
            self.main_splitter.setSizes([500, 500])
            left_v.setSizes([300, 300])
            right_v.setSizes([300, 300])

    def _warn_not_connected(self, action_name: str) -> None:
        """Show polished modal warning when an action requires an active SSH connection."""
        dlg = LogStreamerNoConnectionDialog(action_name=action_name, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.connect_requested.emit()

    def apply_preset(self, preset_key: str, notify_if_disconnected: bool = False) -> None:
        """Apply a built-in log preset."""
        for k, btn in self.preset_btns.items():
            btn.setStyleSheet(self._preset_btn_style(active=(k == preset_key)))

        if self._connection is None and notify_if_disconnected:
            self._warn_not_connected(f"Apply Preset ({preset_key})")

        # Stop existing streams
        AsyncRuntime.instance().submit(self._manager.stop_all_streams())
        for pane in self._panes.values():
            pane.setParent(None)
            pane.deleteLater()
        self._panes.clear()

        # Build configurations for chosen preset
        configs: list[LogStreamConfig] = []
        if preset_key == "nginx-dual":
            configs = [
                LogStreamConfig(name="Nginx Access", target_path="/var/log/nginx/access.log", category="web"),
                LogStreamConfig(name="Nginx Error", target_path="/var/log/nginx/error.log", category="web"),
            ]
        elif preset_key == "security":
            configs = [
                LogStreamConfig(name="Auth / Security", target_path="/var/log/auth.log", use_sudo=True, category="security"),
                LogStreamConfig(name="System Syslog", target_path="/var/log/syslog", category="system"),
            ]
        elif preset_key == "web-db":
            configs = [
                LogStreamConfig(name="Nginx Error", target_path="/var/log/nginx/error.log", category="web"),
                LogStreamConfig(name="PostgreSQL", target_path="/var/log/postgresql/postgresql-16-main.log", category="database"),
            ]
        elif preset_key == "apache":
            configs = [
                LogStreamConfig(name="Apache Access", target_path="/var/log/apache2/access.log", category="web"),
                LogStreamConfig(name="Apache Error", target_path="/var/log/apache2/error.log", category="web"),
            ]
        elif preset_key == "docker":
            configs = [
                LogStreamConfig(name="Docker Daemon", target_path="/var/log/docker.log", category="container"),
                LogStreamConfig(name="Docker Journal", source_type=LogSourceType.JOURNAL, unit_name="docker.service", category="container"),
            ]

        for cfg in configs:
            self._create_pane_for_config(cfg)

        self._rebuild_splitter()

    def _create_pane_for_config(self, config: LogStreamConfig) -> LogStreamPane:
        pane = LogStreamPane(config, parent=self)
        pane.pause_toggled.connect(self._on_pane_pause_toggled)
        pane.close_requested.connect(self._on_pane_close_requested)
        pane.clear_requested.connect(self._on_pane_clear_requested)

        self._panes[config.id] = pane

        # Start stream in background if connection is open
        if self._connection is not None:
            AsyncRuntime.instance().submit(
                self._manager.start_stream(
                    config,
                    self._connection,
                    lambda entry, p=pane: p.append_log_entry(entry),
                )
            )

        return pane

    def open_new_stream_dialog(self) -> None:
        if self._connection is None:
            self._warn_not_connected("Add Custom Log Stream")
            return
        dlg = NewLogStreamDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg = dlg.get_config()
            self._create_pane_for_config(cfg)
            self._rebuild_splitter()

    def _on_pane_pause_toggled(self, stream_id: str, paused: bool) -> None:
        if not paused and self._connection is None:
            self._warn_not_connected("Resume Stream")
            pane = self._panes.get(stream_id)
            if pane:
                pane.set_status(LogStreamStatus.STOPPED)
            return
        if paused:
            self._manager.pause_stream(stream_id)
        else:
            self._manager.resume_stream(stream_id)

    def _on_pane_close_requested(self, stream_id: str) -> None:
        pane = self._panes.pop(stream_id, None)
        if pane:
            AsyncRuntime.instance().submit(self._manager.stop_stream(stream_id))
            pane.setParent(None)
            pane.deleteLater()
            self._rebuild_splitter()

    def _on_pane_clear_requested(self, stream_id: str) -> None:
        self._manager.clear_stream_buffer(stream_id)

    def toggle_global_pause(self) -> None:
        if self._connection is None and self._global_paused:
            self._warn_not_connected("Resume All Streams")
            return
        self._global_paused = not self._global_paused
        for stream_id, pane in self._panes.items():
            if self._global_paused:
                self._manager.pause_stream(stream_id)
                pane.set_status(LogStreamStatus.PAUSED)
            else:
                self._manager.resume_stream(stream_id)
                pane.set_status(LogStreamStatus.STREAMING)

        self.global_pause_btn.setText("▶ Resume All" if self._global_paused else "❚❚ Pause All")

    def clear_all_streams(self) -> None:
        for stream_id, pane in self._panes.items():
            pane.clear_buffer()
            self._manager.clear_stream_buffer(stream_id)

    def _toggle_sync_scroll(self, checked: bool) -> None:
        self._sync_scroll = checked

    def _refresh_kpis(self) -> None:
        """Update KPI summary cards every second."""
        stats = self._manager.get_stats()
        active = stats.get("active_streams", 0)
        total = stats.get("total_streams", 0)
        vel = stats.get("total_velocity", 0.0)
        lines = stats.get("total_lines", 0)

        self.active_badge.setText(f"{active} Streams Live ({vel:.1f} l/s)")

        card_str_val = self.card_streams.findChild(QLabel, "val")
        if card_str_val:
            card_str_val.setText(f"{active} Streams Live")
        card_str_sub = self.card_streams.findChild(QLabel, "sub")
        if card_str_sub:
            names = " • ".join(p.config.name for p in list(self._panes.values())[:2]) or "No streams configured"
            card_str_sub.setText(names)

        card_vel_val = self.card_velocity.findChild(QLabel, "val")
        if card_vel_val:
            card_vel_val.setText(f"{vel:.1f} lines/s")

        card_buf_val = self.card_buffer.findChild(QLabel, "val")
        if card_buf_val:
            card_buf_val.setText(f"{lines:,} lines")

        # Update each pane's velocity badge from session
        for stream_id, pane in self._panes.items():
            sess = self._manager.get_session(stream_id)
            if sess:
                pane.update_velocity(sess.velocity)
                if sess.status != pane._status:
                    pane.set_status(sess.status)
