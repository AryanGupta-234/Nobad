from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.health_monitor import format_bytes
from core.services_manager import ServiceJournalEntry, ServiceUnitInfo
from ui.dashboard_components import hex_to_rgba
from ui.icons import get_icon


class ServiceCardWidget(QFrame):
    """
    Master-detail service card matching Raycast / Linear design.
    Displays unit state, listening ports, resource telemetry, inline boot toggle, and actions.
    """

    clicked = Signal(str)                          # unit_name
    action_requested = Signal(str, str)            # unit_name, action ("start", "stop", "restart", "reload")
    boot_toggled = Signal(str, bool)               # unit_name, enabled
    edit_requested = Signal(str)                   # unit_name

    def __init__(self, service: ServiceUnitInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._is_selected = False

        self.setObjectName("ServiceCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._build_ui()
        self.update_selection(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Top Row: Status Beacon + Unit Name + State Badges on Left; Boot & Controls on Right
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Status Beacon Icon Box
        self.beacon_box = QLabel()
        self.beacon_box.setFixedSize(26, 26)
        self.beacon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.beacon_box)

        # Title & Badges Box
        name_box = QHBoxLayout()
        name_box.setSpacing(6)

        self.name_label = QLabel(self._service.name)
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 700; font-family: monospace; color: #ffffff;")
        name_box.addWidget(self.name_label)

        self.state_badge = QLabel()
        name_box.addWidget(self.state_badge)

        if self._service.ports:
            self.ports_badge = QLabel(self._service.ports)
            self.ports_badge.setStyleSheet(
                "background-color: rgba(56, 189, 248, 0.12); color: #38bdf8; "
                "border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 4px; "
                "padding: 1px 6px; font-size: 10px; font-family: monospace; font-weight: 600;"
            )
            name_box.addWidget(self.ports_badge)

        name_box.addStretch(1)
        top_row.addLayout(name_box)

        # Right Inline Actions & Boot Toggle
        right_box = QHBoxLayout()
        right_box.setSpacing(10)

        # Boot persistence switch
        boot_box = QHBoxLayout()
        boot_box.setSpacing(4)
        boot_lbl = QLabel("Boot:")
        boot_lbl.setStyleSheet("font-size: 10px; font-family: monospace; font-weight: 600; color: #818cf8;")
        boot_box.addWidget(boot_lbl)

        self.boot_check = QCheckBox()
        self.boot_check.setChecked(self._service.is_boot_enabled)
        self.boot_check.setToolTip("systemctl enable / disable unit on boot")
        self.boot_check.toggled.connect(self._on_boot_toggled)
        self.boot_check.setStyleSheet(
            """
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid #3b3b4f;
                background-color: #171720;
            }
            QCheckBox::indicator:checked {
                background-color: #6366f1;
                border-color: #6366f1;
            }
            """
        )
        boot_box.addWidget(self.boot_check)
        right_box.addLayout(boot_box)

        # Action Buttons
        self._build_actions(right_box)

        top_row.addLayout(right_box)
        layout.addLayout(top_row)

        # Middle Row: Description
        if self._service.description:
            self.desc_label = QLabel(self._service.description)
            desc_color = "#f87171" if self._service.is_failed else "#94a3b8"
            self.desc_label.setStyleSheet(f"font-size: 11px; color: {desc_color}; background: transparent;")
            self.desc_label.setWordWrap(True)
            layout.addWidget(self.desc_label)

        # Bottom Row: Telemetry Chips (PID, Mem, CPU, Uptime)
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)

        pid_str = str(self._service.pid) if self._service.pid > 0 else "-"
        self.pid_label = QLabel(f"PID: <b style='color: #cbd5e1;'>{pid_str}</b>")
        self.pid_label.setTextFormat(Qt.TextFormat.RichText)
        self.pid_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #64748b;")
        metrics_row.addWidget(self.pid_label)

        mem_str = format_bytes(self._service.memory_bytes) if self._service.memory_bytes > 0 else "-"
        self.mem_label = QLabel(f"Mem: <b style='color: #cbd5e1;'>{mem_str}</b>")
        self.mem_label.setTextFormat(Qt.TextFormat.RichText)
        self.mem_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #64748b;")
        metrics_row.addWidget(self.mem_label)

        cat_str = self._service.category.capitalize()
        self.cat_label = QLabel(f"Category: <b style='color: #a78bfa;'>{cat_str}</b>")
        self.cat_label.setTextFormat(Qt.TextFormat.RichText)
        self.cat_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #64748b;")
        metrics_row.addWidget(self.cat_label)

        metrics_row.addStretch(1)
        layout.addLayout(metrics_row)

        self._apply_state_styling()

    def _build_actions(self, container: QHBoxLayout) -> None:
        btn_box = QHBoxLayout()
        btn_box.setSpacing(4)

        if self._service.is_failed:
            # Failed unit: prominent Restart/Recover button
            restart_btn = QPushButton("Restart Unit")
            restart_btn.setFixedHeight(24)
            restart_btn.setStyleSheet(
                "background-color: #e11d48; color: #ffffff; border: none; border-radius: 5px; "
                "font-size: 11px; font-weight: 700; padding: 2px 10px;"
            )
            restart_btn.clicked.connect(lambda: self.action_requested.emit(self._service.name, "restart"))
            btn_box.addWidget(restart_btn)
        elif self._service.is_running:
            # Running unit: Restart, Reload, Stop
            restart_btn = QPushButton("Restart")
            restart_btn.setFixedHeight(22)
            restart_btn.setStyleSheet(
                "background-color: #171720; border: 1px solid #2b2b3a; color: #fbbf24; border-radius: 4px; "
                "padding: 2px 8px; font-size: 11px; font-weight: 600;"
            )
            restart_btn.clicked.connect(lambda: self.action_requested.emit(self._service.name, "restart"))
            btn_box.addWidget(restart_btn)

            reload_btn = QPushButton("Reload")
            reload_btn.setFixedHeight(22)
            reload_btn.setStyleSheet(
                "background-color: #171720; border: 1px solid #2b2b3a; color: #38bdf8; border-radius: 4px; "
                "padding: 2px 8px; font-size: 11px; font-weight: 600;"
            )
            reload_btn.clicked.connect(lambda: self.action_requested.emit(self._service.name, "reload"))
            btn_box.addWidget(reload_btn)

            stop_btn = QPushButton("Stop")
            stop_btn.setFixedHeight(22)
            stop_btn.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); color: #f87171; "
                "border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600;"
            )
            stop_btn.clicked.connect(lambda: self.action_requested.emit(self._service.name, "stop"))
            btn_box.addWidget(stop_btn)
        else:
            # Stopped unit: Start button
            start_btn = QPushButton("Start")
            start_btn.setFixedHeight(22)
            start_btn.setStyleSheet(
                "background-color: #10b981; color: #ffffff; border: none; border-radius: 4px; "
                "padding: 2px 10px; font-size: 11px; font-weight: 700;"
            )
            start_btn.clicked.connect(lambda: self.action_requested.emit(self._service.name, "start"))
            btn_box.addWidget(start_btn)

        # Edit unit file button
        edit_btn = QPushButton("✎ Edit")
        edit_btn.setFixedHeight(22 if self._service.is_running else 24)
        edit_btn.setToolTip(f"Open {self._service.name} unit file in Code Editor")
        edit_btn.setStyleSheet(
            "background-color: #171720; border: 1px solid #2b2b3a; color: #a5b4fc; border-radius: 4px; "
            "padding: 2px 8px; font-size: 11px; font-weight: 600;"
        )
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._service.name))
        btn_box.addWidget(edit_btn)

        container.addLayout(btn_box)

    def _apply_state_styling(self) -> None:
        if self._service.is_failed:
            self.beacon_box.setText("✖")
            self.beacon_box.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 6px; font-weight: bold; font-size: 12px;"
            )
            self.state_badge.setText(f"failed ({self._service.sub_state})")
            self.state_badge.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.12); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 4px; padding: 1px 6px; font-size: 10px; font-family: monospace; font-weight: 600;"
            )
        elif self._service.is_running:
            self.beacon_box.setText("●")
            self.beacon_box.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 6px; font-size: 14px;"
            )
            self.state_badge.setText("active (running)")
            self.state_badge.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.12); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 4px; padding: 1px 6px; font-size: 10px; font-family: monospace; font-weight: 600;"
            )
        else:
            self.beacon_box.setText("○")
            self.beacon_box.setStyleSheet(
                "background-color: rgba(148, 163, 184, 0.1); color: #64748b; border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 6px; font-size: 14px;"
            )
            self.state_badge.setText(f"{self._service.active_state} ({self._service.sub_state})")
            self.state_badge.setStyleSheet(
                "background-color: #171720; color: #94a3b8; border: 1px solid #2b2b3a; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-family: monospace; font-weight: 600;"
            )

    def update_selection(self, selected: bool) -> None:
        self._is_selected = selected
        border_color = "#6366f1" if selected else "#242430"
        bg_color = "rgba(99, 102, 241, 0.08)" if selected else "#15151c"

        self.setStyleSheet(
            f"""
            QFrame#ServiceCard {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
            QFrame#ServiceCard:hover {{
                border-color: {"#6366f1" if selected else "#3b3b4f"};
            }}
            """
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._service.name)
        super().mousePressEvent(event)

    def _on_boot_toggled(self, checked: bool) -> None:
        self.boot_toggled.emit(self._service.name, checked)


class ServiceJournalConsoleWidget(QFrame):
    """Monospace dark terminal console for viewing live systemd journal logs."""

    copy_requested = Signal()
    open_terminal_requested = Signal()
    filter_changed = Signal(bool)  # errors_only

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("JournalConsole")
        self.setStyleSheet(
            """
            QFrame#JournalConsole {
                background-color: #09090b;
                border: 1px solid #1f1f28;
                border-radius: 8px;
            }
            """
        )
        self._errors_only = False
        self._raw_entries: tuple[ServiceJournalEntry, ...] = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Toolbar Header
        tb = QHBoxLayout()
        tb.setSpacing(8)

        self.stream_lbl = QLabel("● journalctl stream")
        self.stream_lbl.setStyleSheet("font-size: 11px; font-family: monospace; font-weight: 700; color: #34d399;")
        tb.addWidget(self.stream_lbl)

        tb.addStretch(1)

        # Errors-only toggle
        self.btn_all = QPushButton("All")
        self.btn_all.setFixedHeight(20)
        self.btn_err = QPushButton("Errors (-p err)")
        self.btn_err.setFixedHeight(20)

        for b in (self.btn_all, self.btn_err):
            b.setCheckable(True)
            b.setStyleSheet(
                """
                QPushButton {
                    background-color: #171720;
                    border: 1px solid #2b2b3a;
                    color: #94a3b8;
                    border-radius: 4px;
                    padding: 1px 7px;
                    font-size: 10px;
                    font-weight: 600;
                }
                QPushButton:checked {
                    background-color: #2b2b3a;
                    color: #ffffff;
                    border-color: #434358;
                }
                """
            )
        self.btn_all.setChecked(True)
        self.btn_all.clicked.connect(lambda: self._set_filter(False))
        self.btn_err.clicked.connect(lambda: self._set_filter(True))
        tb.addWidget(self.btn_all)
        tb.addWidget(self.btn_err)

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedHeight(20)
        copy_btn.setStyleSheet(
            "background-color: #171720; border: 1px solid #2b2b3a; color: #cbd5e1; border-radius: 4px; "
            "padding: 1px 7px; font-size: 10px; font-weight: 600;"
        )
        copy_btn.clicked.connect(self.copy_requested.emit)
        tb.addWidget(copy_btn)

        layout.addLayout(tb)

        # Monospace Text Box
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            """
            QTextEdit {
                background-color: transparent;
                border: none;
                color: #e2e8f0;
                font-family: 'JetBrains Mono', 'Fira Code', monospace;
                font-size: 11px;
                line-height: 140%;
            }
            """
        )
        layout.addWidget(self.text_edit)

    def set_logs(self, unit_name: str, entries: tuple[ServiceJournalEntry, ...]) -> None:
        self._raw_entries = entries
        self.stream_lbl.setText(f"● journalctl -u {unit_name} -n 50")
        self._render_text()

    def _set_filter(self, errors_only: bool) -> None:
        self._errors_only = errors_only
        self.btn_all.setChecked(not errors_only)
        self.btn_err.setChecked(errors_only)
        self._render_text()
        self.filter_changed.emit(errors_only)

    def _render_text(self) -> None:
        if not self._raw_entries:
            self.text_edit.setHtml("<span style='color: #64748b;'>No journal logs recorded for this unit.</span>")
            return

        lines: list[str] = []
        for e in self._raw_entries:
            if self._errors_only and not e.is_error:
                continue

            color = "#f87171" if e.is_error else "#cbd5e1"
            sender_color = "#818cf8"
            time_color = "#64748b"

            safe_msg = e.message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            line_html = (
                f"<div style='margin-bottom: 3px; font-family: monospace;'>"
                f"<span style='color: {time_color};'>{e.timestamp}</span> "
                f"<span style='color: {sender_color}; font-weight: bold;'>{e.sender}</span> "
                f"<span style='color: {color};'>{safe_msg}</span>"
                f"</div>"
            )
            lines.append(line_html)

        self.text_edit.setHtml("".join(lines))
        # Scroll to bottom
        sb = self.text_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def get_plain_text(self) -> str:
        return "\n".join(f"{e.timestamp} {e.sender} {e.message}" for e in self._raw_entries)


class ServiceInspectorWidget(QFrame):
    """Right-hand side deep inspector panel for selected systemd service."""

    action_requested = Signal(str, str)
    edit_requested = Signal(str)
    terminal_requested = Signal(str)
    reload_logs_requested = Signal(str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ServiceInspector")
        self.setStyleSheet(
            """
            QFrame#ServiceInspector {
                background-color: #121217;
                border-left: 1px solid #242430;
            }
            """
        )
        self._current_unit: str = ""
        self._current_unit_path: str = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header: Unit Name + Badge + Path
        head_box = QVBoxLayout()
        head_box.setSpacing(4)

        top_h = QHBoxLayout()
        top_h.setSpacing(8)
        self.title_label = QLabel("Select a Service")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700; font-family: monospace; color: #ffffff;")
        top_h.addWidget(self.title_label)

        self.status_badge = QLabel("")
        top_h.addWidget(self.status_badge)
        top_h.addStretch(1)
        head_box.addLayout(top_h)

        self.desc_label = QLabel("Inspect real-time CGroup telemetry, PID, and live journal logs.")
        self.desc_label.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.desc_label.setWordWrap(True)
        head_box.addWidget(self.desc_label)

        self.path_label = QLabel("/lib/systemd/system/")
        self.path_label.setStyleSheet("font-size: 10px; font-family: monospace; color: #64748b;")
        head_box.addWidget(self.path_label)

        layout.addLayout(head_box)

        # Action Buttons Toolbar
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self.start_btn = QPushButton("Start")
        self.start_btn.setStyleSheet(
            "background-color: #10b981; border: none; color: #ffffff; border-radius: 6px; "
            "padding: 5px 14px; font-size: 11px; font-weight: 700;"
        )
        self.start_btn.clicked.connect(lambda: self.action_requested.emit(self._current_unit, "start"))
        action_row.addWidget(self.start_btn)

        self.restart_btn = QPushButton("Restart")
        self.restart_btn.setStyleSheet(
            "background-color: #1b1b24; border: 1px solid #2b2b3a; color: #fbbf24; border-radius: 6px; "
            "padding: 5px 12px; font-size: 11px; font-weight: 600;"
        )
        self.restart_btn.clicked.connect(lambda: self.action_requested.emit(self._current_unit, "restart"))
        action_row.addWidget(self.restart_btn)

        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setStyleSheet(
            "background-color: #1b1b24; border: 1px solid #2b2b3a; color: #38bdf8; border-radius: 6px; "
            "padding: 5px 12px; font-size: 11px; font-weight: 600;"
        )
        self.reload_btn.clicked.connect(lambda: self.action_requested.emit(self._current_unit, "reload"))
        action_row.addWidget(self.reload_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet(
            "background-color: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); color: #f87171; "
            "border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600;"
        )
        self.stop_btn.clicked.connect(lambda: self.action_requested.emit(self._current_unit, "stop"))
        action_row.addWidget(self.stop_btn)

        self.edit_btn = QPushButton("✎ Edit Unit")
        self.edit_btn.setToolTip("Open unit file in Code Editor Studio (e.g. /lib/systemd/system/...)")
        self.edit_btn.setStyleSheet(
            "background-color: #1b1b24; border: 1px solid #3b3b4f; color: #a5b4fc; border-radius: 6px; "
            "padding: 5px 12px; font-size: 11px; font-weight: 600;"
        )
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        action_row.addWidget(self.edit_btn)

        action_row.addStretch(1)
        layout.addLayout(action_row)

        # CGroup Specs Grid (2x2)
        specs_frame = QFrame()
        specs_frame.setStyleSheet(
            "background-color: #171720; border: 1px solid #262634; border-radius: 8px; padding: 10px;"
        )
        specs_l = QVBoxLayout(specs_frame)
        specs_l.setContentsMargins(10, 8, 10, 8)
        specs_l.setSpacing(6)

        specs_title = QLabel("UNIT TELEMETRY & CGROUP SPECS")
        specs_title.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        specs_l.addWidget(specs_title)

        grid = QHBoxLayout()
        grid.setSpacing(12)

        col1 = QVBoxLayout()
        col1.setSpacing(4)
        self.pid_val = QLabel("Main PID: -")
        self.pid_val.setStyleSheet("font-size: 11px; font-family: monospace; color: #cbd5e1;")
        col1.addWidget(self.pid_val)

        self.mem_val = QLabel("Memory: -")
        self.mem_val.setStyleSheet("font-size: 11px; font-family: monospace; color: #cbd5e1;")
        col1.addWidget(self.mem_val)
        grid.addLayout(col1)

        col2 = QVBoxLayout()
        col2.setSpacing(4)
        self.restart_val = QLabel("Restart: always")
        self.restart_val.setStyleSheet("font-size: 11px; font-family: monospace; color: #cbd5e1;")
        col2.addWidget(self.restart_val)

        self.tasks_val = QLabel("Tasks: -")
        self.tasks_val.setStyleSheet("font-size: 11px; font-family: monospace; color: #cbd5e1;")
        col2.addWidget(self.tasks_val)
        grid.addLayout(col2)

        specs_l.addLayout(grid)

        # ExecStart Preview
        self.exec_label = QLabel("ExecStart: -")
        self.exec_label.setStyleSheet(
            "font-size: 10px; font-family: monospace; color: #818cf8; background-color: #0e0e14; "
            "border: 1px solid #21212c; border-radius: 4px; padding: 4px 6px;"
        )
        self.exec_label.setWordWrap(True)
        specs_l.addWidget(self.exec_label)

        layout.addWidget(specs_frame)

        # Journal Console Widget
        self.console = ServiceJournalConsoleWidget(self)
        self.console.copy_requested.connect(self._copy_console_logs)
        self.console.filter_changed.connect(self._on_log_filter_changed)
        layout.addWidget(self.console, 1)

    def _on_edit_clicked(self) -> None:
        path = self._current_unit_path or f"/lib/systemd/system/{self._current_unit}"
        self.edit_requested.emit(path)

    def set_service(self, s: ServiceUnitInfo, props: dict[str, str] | None = None) -> None:
        self._current_unit = s.name
        self.title_label.setText(s.name)
        self.desc_label.setText(s.description or "No description provided.")

        props = props or {}
        fragment_path = props.get("FragmentPath")
        if not fragment_path or not fragment_path.startswith("/"):
            fragment_path = f"/lib/systemd/system/{s.name}"
        self._current_unit_path = fragment_path
        self.path_label.setText(f"{fragment_path} ({s.load_state}; {s.unit_file_state})")

        # Action button state
        self.start_btn.setVisible(not s.is_running)
        self.stop_btn.setVisible(s.is_running)
        self.restart_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.edit_btn.setEnabled(True)
        self.edit_btn.setToolTip(f"Open {fragment_path} in Code Editor Studio")

        # Status badge
        if s.is_failed:
            self.status_badge.setText(f"● failed ({s.sub_state})")
            self.status_badge.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: monospace; font-weight: 700;"
            )
        elif s.is_running:
            self.status_badge.setText("● active (running)")
            self.status_badge.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: monospace; font-weight: 700;"
            )
        else:
            self.status_badge.setText(f"○ {s.active_state} ({s.sub_state})")
            self.status_badge.setStyleSheet(
                "background-color: #171720; color: #94a3b8; border: 1px solid #2b2b3a; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: monospace; font-weight: 700;"
            )

        # Properties
        props = props or {}
        pid_str = props.get("MainPID", str(s.pid) if s.pid > 0 else "-")
        self.pid_val.setText(f"Main PID: {pid_str}")

        mem_bytes = int(props.get("MemoryCurrent", s.memory_bytes)) if props.get("MemoryCurrent", "").isdigit() else s.memory_bytes
        self.mem_val.setText(f"Memory: {format_bytes(mem_bytes) if mem_bytes > 0 else '-'}")

        self.restart_val.setText(f"Restart: {props.get('Restart', s.restart_policy)}")
        tasks_curr = props.get("TasksCurrent", "-")
        tasks_max = props.get("TasksMax", "-")
        self.tasks_val.setText(f"Tasks: {tasks_curr} / {tasks_max}")

        exec_cmd = props.get("ExecStart", s.exec_start) or "-"
        self.exec_label.setText(f"ExecStart: {exec_cmd}")

    def _copy_console_logs(self) -> None:
        text = self.console.get_plain_text()
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        if cb:
            cb.setText(text)

    def _on_log_filter_changed(self, errors_only: bool) -> None:
        if self._current_unit:
            self.reload_logs_requested.emit(self._current_unit, errors_only)


class ServiceDenseTableView(QTableWidget):
    """High-density tabular view for system administrators."""

    action_requested = Signal(str, str)
    unit_selected = Signal(str)
    edit_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels([
            "UNIT FILE", "STATE", "BOOT ENABLED", "PID", "CPU", "MEMORY", "PORTS / SOCKETS", "ACTIONS"
        ])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.setStyleSheet(
            """
            QTableWidget {
                background-color: #101014;
                alternate-background-color: #14141a;
                border: 1px solid #22222c;
                border-radius: 8px;
                color: #e2e8f0;
                font-family: monospace;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #1a1a22;
            }
            QTableWidget::item:hover {
                background-color: #1d1d26;
            }
            QHeaderView::section {
                background-color: #16161e;
                color: #cbd5e1;
                padding: 7px 10px;
                border: none;
                border-bottom: 1px solid #282834;
                font-weight: 700;
                font-size: 10px;
                text-align: left;
            }
            """
        )
        self.itemClicked.connect(self._on_item_clicked)

    def set_services(self, services: tuple[ServiceUnitInfo, ...]) -> None:
        self.setRowCount(len(services))
        for row, s in enumerate(services):
            # 0: Unit Name
            item_name = QTableWidgetItem(s.name)
            item_name.setForeground(QColor("#ffffff"))
            self.setItem(row, 0, item_name)

            # 1: State
            state_text = f"{s.active_state} ({s.sub_state})"
            item_state = QTableWidgetItem(state_text)
            color = "#34d399" if s.is_running else ("#ef4444" if s.is_failed else "#94a3b8")
            item_state.setForeground(QColor(color))
            self.setItem(row, 1, item_state)

            # 2: Boot Enabled
            item_boot = QTableWidgetItem(s.unit_file_state)
            item_boot.setForeground(QColor("#818cf8" if s.is_boot_enabled else "#64748b"))
            self.setItem(row, 2, item_boot)

            # 3: PID
            pid_str = str(s.pid) if s.pid > 0 else "-"
            item_pid = QTableWidgetItem(pid_str)
            item_pid.setForeground(QColor("#cbd5e1"))
            self.setItem(row, 3, item_pid)

            # 4: CPU
            item_cpu = QTableWidgetItem("-")
            item_cpu.setForeground(QColor("#34d399"))
            item_cpu.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, 4, item_cpu)

            # 5: Memory
            mem_str = format_bytes(s.memory_bytes) if s.memory_bytes > 0 else "-"
            item_mem = QTableWidgetItem(mem_str)
            item_mem.setForeground(QColor("#cbd5e1"))
            item_mem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, 5, item_mem)

            # 6: Ports
            item_ports = QTableWidgetItem(s.ports or "-")
            item_ports.setForeground(QColor("#38bdf8" if s.ports else "#64748b"))
            self.setItem(row, 6, item_ports)

            # 7: Actions Button Widget
            btn_w = QWidget()
            btn_l = QHBoxLayout(btn_w)
            btn_l.setContentsMargins(2, 2, 2, 2)
            btn_l.setSpacing(4)

            btn = QPushButton("Restart" if s.is_running or s.is_failed else "Start")
            btn.setFixedHeight(20)
            btn.setStyleSheet(
                "background-color: #1c1c26; border: 1px solid #2b2b3a; color: #e2e8f0; "
                "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            )
            act = "restart" if s.is_running or s.is_failed else "start"
            btn.clicked.connect((lambda name=s.name, a=act: lambda: self.action_requested.emit(name, a))())
            btn_l.addWidget(btn)

            edit_btn = QPushButton("✎ Edit")
            edit_btn.setFixedHeight(20)
            edit_btn.setToolTip(f"Open {s.name} unit file in Code Editor")
            edit_btn.setStyleSheet(
                "background-color: #1c1c26; border: 1px solid #2b2b3a; color: #a5b4fc; "
                "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            )
            edit_btn.clicked.connect((lambda name=s.name: lambda: self.edit_requested.emit(name))())
            btn_l.addWidget(edit_btn)

            self.setCellWidget(row, 7, btn_w)

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        unit = self.item(item.row(), 0)
        if unit:
            self.unit_selected.emit(unit.text())


class NewUnitModalDialog(QDialog):
    """
    Template generator modal for systemd service unit files.
    Allows 1-click generation for FastAPI, Celery, Node.js, and Docker Compose.
    """

    UNIT_PRESETS: dict[str, dict[str, str]] = {
        "fastapi": {
            "name": "fastapi-backend.service",
            "user": "www-data",
            "group": "www-data",
            "workdir": "/opt/my-app",
            "exec": "/opt/my-app/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000",
            "content": (
                "[Unit]\nDescription=FastAPI Async Backend Service\nAfter=network.target\n\n"
                "[Service]\nType=simple\nUser=www-data\nGroup=www-data\nWorkingDirectory=/opt/my-app\n"
                "ExecStart=/opt/my-app/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000\n"
                "Restart=always\nRestartSec=3\nEnvironment=\"PYTHONUNBUFFERED=1\"\n\n"
                "[Install]\nWantedBy=multi-user.target\n"
            ),
        },
        "celery": {
            "name": "celery-worker.service",
            "user": "ubuntu",
            "group": "ubuntu",
            "workdir": "/opt/my-app",
            "exec": "/opt/my-app/venv/bin/celery -A tasks worker --loglevel=INFO",
            "content": (
                "[Unit]\nDescription=Celery Distributed Task Worker\nAfter=network.target redis.service\n\n"
                "[Service]\nType=forking\nUser=ubuntu\nGroup=ubuntu\nWorkingDirectory=/opt/my-app\n"
                "ExecStart=/opt/my-app/venv/bin/celery -A tasks worker --loglevel=INFO\n"
                "Restart=on-failure\nRestartSec=5\n\n"
                "[Install]\nWantedBy=multi-user.target\n"
            ),
        },
        "node": {
            "name": "nextjs-web.service",
            "user": "node",
            "group": "node",
            "workdir": "/var/www/nextjs-app",
            "exec": "/usr/bin/npm start",
            "content": (
                "[Unit]\nDescription=Next.js Web Application\nAfter=network.target\n\n"
                "[Service]\nType=simple\nUser=node\nGroup=node\nWorkingDirectory=/var/www/nextjs-app\n"
                "ExecStart=/usr/bin/npm start\nRestart=always\nRestartSec=5\n"
                "Environment=\"NODE_ENV=production\" \"PORT=3000\"\n\n"
                "[Install]\nWantedBy=multi-user.target\n"
            ),
        },
        "compose": {
            "name": "docker-compose-stack.service",
            "user": "root",
            "group": "root",
            "workdir": "/opt/docker-stack",
            "exec": "/usr/bin/docker compose up -d",
            "content": (
                "[Unit]\nDescription=Docker Compose Stack Service\nRequires=docker.service\nAfter=docker.service\n\n"
                "[Service]\nType=oneshot\nRemainAfterExit=yes\nWorkingDirectory=/opt/docker-stack\n"
                "ExecStart=/usr/bin/docker compose up -d\nExecStop=/usr/bin/docker compose down\n"
                "TimeoutStartSec=0\n\n[Install]\nWantedBy=multi-user.target\n"
            ),
        },
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create & Install Systemd Service Unit")
        self.setFixedSize(680, 600)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #14141c;
                border: 1px solid #282838;
                border-radius: 12px;
            }
            """
        )
        self._build_ui()
        self._apply_preset("fastapi")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Header
        h_box = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon("services").pixmap(22, 22))
        h_box.addWidget(icon_lbl)

        title_l = QVBoxLayout()
        title = QLabel("Create & Install Systemd Service Unit")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        title_l.addWidget(title)
        sub = QLabel("Generates a production unit file in /etc/systemd/system/ and triggers daemon-reload")
        sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        title_l.addWidget(sub)
        h_box.addLayout(title_l)
        h_box.addStretch(1)
        layout.addLayout(h_box)

        # Preset Buttons Row
        preset_box = QHBoxLayout()
        preset_box.setSpacing(8)
        for key, label in (("fastapi", "FastAPI / Uvicorn"), ("celery", "Celery Worker"), ("node", "Node.js / Express"), ("compose", "Docker Compose")):
            btn = QPushButton(label)
            btn.setStyleSheet(
                "background-color: #1a1a24; border: 1px solid #2c2c3e; color: #e2e8f0; border-radius: 6px; "
                "padding: 5px 10px; font-size: 11px; font-weight: 600;"
            )
            btn.clicked.connect((lambda k=key: lambda: self._apply_preset(k))())
            preset_box.addWidget(btn)
        layout.addLayout(preset_box)

        # Name & User inputs
        form_grid = QHBoxLayout()
        form_grid.setSpacing(10)

        name_col = QVBoxLayout()
        name_col.setSpacing(3)
        name_col.addWidget(QLabel("Unit Name (.service)"))
        self.name_input = QLineEdit("fastapi-backend.service")
        self.name_input.setStyleSheet("background-color: #101015; border: 1px solid #2b2b3a; border-radius: 6px; padding: 5px; color: #ffffff; font-family: monospace;")
        self.name_input.textChanged.connect(self._sync_content)
        name_col.addWidget(self.name_input)
        form_grid.addLayout(name_col)

        user_col = QVBoxLayout()
        user_col.setSpacing(3)
        user_col.addWidget(QLabel("Execution User"))
        self.user_input = QLineEdit("www-data")
        self.user_input.setStyleSheet("background-color: #101015; border: 1px solid #2b2b3a; border-radius: 6px; padding: 5px; color: #ffffff; font-family: monospace;")
        self.user_input.textChanged.connect(self._sync_content)
        user_col.addWidget(self.user_input)
        form_grid.addLayout(user_col)

        layout.addLayout(form_grid)

        # WorkDir & Exec
        wd_col = QVBoxLayout()
        wd_col.setSpacing(3)
        wd_col.addWidget(QLabel("Working Directory"))
        self.workdir_input = QLineEdit("/opt/my-app")
        self.workdir_input.setStyleSheet("background-color: #101015; border: 1px solid #2b2b3a; border-radius: 6px; padding: 5px; color: #ffffff; font-family: monospace;")
        self.workdir_input.textChanged.connect(self._sync_content)
        wd_col.addWidget(self.workdir_input)
        layout.addLayout(wd_col)

        exec_col = QVBoxLayout()
        exec_col.setSpacing(3)
        exec_col.addWidget(QLabel("ExecStart Command"))
        self.exec_input = QLineEdit("/opt/my-app/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000")
        self.exec_input.setStyleSheet("background-color: #101015; border: 1px solid #2b2b3a; border-radius: 6px; padding: 5px; color: #ffffff; font-family: monospace;")
        self.exec_input.textChanged.connect(self._sync_content)
        exec_col.addWidget(self.exec_input)
        layout.addLayout(exec_col)

        # INI Code preview
        layout.addWidget(QLabel("Unit File Content Preview (/etc/systemd/system/...)"))
        self.preview_edit = QTextEdit()
        self.preview_edit.setStyleSheet(
            "background-color: #0c0c11; border: 1px solid #242430; border-radius: 6px; color: #e2e8f0; font-family: monospace; font-size: 11px;"
        )
        layout.addWidget(self.preview_edit, 1)

        # Footer Actions
        footer = QHBoxLayout()
        self.auto_start_check = QCheckBox("Enable on boot && Start immediately")
        self.auto_start_check.setChecked(True)
        self.auto_start_check.setStyleSheet("color: #e2e8f0; font-size: 12px;")
        footer.addWidget(self.auto_start_check)

        footer.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background-color: #1b1b24; border: 1px solid #2b2b3a; color: #cbd5e1; border-radius: 6px; padding: 6px 14px;")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        install_btn = QPushButton("Install Unit && Daemon-Reload")
        install_btn.setStyleSheet("background-color: #6366f1; border: none; color: #ffffff; font-weight: 700; border-radius: 6px; padding: 6px 16px;")
        install_btn.clicked.connect(self.accept)
        footer.addWidget(install_btn)

        layout.addLayout(footer)

    def _apply_preset(self, preset_key: str) -> None:
        p = self.UNIT_PRESETS.get(preset_key, {})
        if not p:
            return
        self.name_input.setText(p["name"])
        self.user_input.setText(p["user"])
        self.workdir_input.setText(p["workdir"])
        self.exec_input.setText(p["exec"])
        self.preview_edit.setPlainText(p["content"])

    def _sync_content(self) -> None:
        name = self.name_input.text().strip()
        user = self.user_input.text().strip()
        wd = self.workdir_input.text().strip()
        cmd = self.exec_input.text().strip()

        content = (
            f"[Unit]\nDescription={name} managed by Remote File Manager\nAfter=network.target\n\n"
            f"[Service]\nType=simple\nUser={user}\nWorkingDirectory={wd}\n"
            f"ExecStart={cmd}\nRestart=always\nRestartSec=3\n\n"
            f"[Install]\nWantedBy=multi-user.target\n"
        )
        self.preview_edit.setPlainText(content)

    def accept(self) -> None:
        name = self.unit_name
        from core.services_manager import validate_unit_name
        if not validate_unit_name(name):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Invalid Unit Name",
                f"The unit name '{name}' is invalid.\nUnit names must end with .service and contain only letters, numbers, dots, hyphens, and underscores."
            )
            return
        super().accept()

    @property
    def unit_name(self) -> str:
        return self.name_input.text().strip()

    @property
    def unit_content(self) -> str:
        return self.preview_edit.toPlainText().strip()

    @property
    def enable_and_start(self) -> bool:
        return self.auto_start_check.isChecked()
