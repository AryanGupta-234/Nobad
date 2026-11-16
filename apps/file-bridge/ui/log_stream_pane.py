from __future__ import annotations

import html
import queue
import re
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.log_streamer import LogEntry, LogStreamConfig, LogStreamStatus


class LogStreamPane(QFrame):
    """
    High-performance single log stream pane with real-time batched rendering (60ms),
    sticky auto-scroll lock, regex filtering, and semantic syntax highlighting.
    """

    pause_toggled = Signal(str, bool)      # stream_id, is_paused
    close_requested = Signal(str)          # stream_id
    clear_requested = Signal(str)          # stream_id

    def __init__(self, config: LogStreamConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.stream_id = config.id
        self._status = LogStreamStatus.CONNECTING
        self._wrap = False
        self._auto_scroll = True
        self._pending_new_lines = 0
        self._velocity = 0.0
        self._total_lines = 0

        # Filtering state
        self._filter_query = ""
        self._regex_mode = False
        self._case_sensitive = False
        self._invert_mode = False
        self._level_filter = "all"  # "all", "error", "warn", "2xx"

        # Staging queue and batching timer
        self._queue: queue.SimpleQueue[LogEntry] = queue.SimpleQueue()
        self._all_entries: list[LogEntry] = []

        self._init_ui()

        # Batch timer for smooth 60fps rendering without UI freezes
        self._batch_timer = QTimer(self)
        self._batch_timer.setInterval(60)
        self._batch_timer.timeout.connect(self._flush_batch_queue)
        self._batch_timer.start()

    def _init_ui(self) -> None:
        self.setObjectName("LogStreamPane")
        self.setStyleSheet("""
            QFrame#LogStreamPane {
                background-color: #111116;
                border: 1px solid #1f1f2e;
                border-radius: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top Header Bar
        header = self._build_header()
        layout.addWidget(header)

        # 2. Filter & Level Toolbar
        toolbar = self._build_filter_toolbar()
        layout.addWidget(toolbar)

        # 3. Canvas Container (hosts QPlainTextEdit and floating pill)
        self.canvas_container = QWidget()
        self.canvas_container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(self.canvas_container)
        c_layout.setContentsMargins(8, 8, 8, 8)
        c_layout.setSpacing(0)

        self.canvas = QPlainTextEdit()
        self.canvas.setReadOnly(True)
        self.canvas.setMaximumBlockCount(10000)
        self.canvas.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.canvas.setFont(font)
        self.canvas.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0a0a0f;
                color: #f4f4f5;
                border: 1px solid #181824;
                border-radius: 8px;
                padding: 6px;
                selection-background-color: #312e81;
                selection-color: #ffffff;
            }
            QScrollBar:vertical {
                border: none;
                background: #0d0d12;
                width: 10px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #272738;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3f3f5a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                border: none;
                background: #0d0d12;
                height: 10px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #272738;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #3f3f5a;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
        """)

        # Connect scrollbar for sticky auto-scroll detection
        self.canvas.verticalScrollBar().valueChanged.connect(self._on_vertical_scroll)

        c_layout.addWidget(self.canvas)

        # Floating Auto-Scroll Pill
        self.floating_pill = QPushButton("↓ Auto-scroll paused (0 new lines) — Jump to bottom", self.canvas)
        self.floating_pill.setObjectName("FloatingPill")
        self.floating_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.floating_pill.setStyleSheet("""
            QPushButton#FloatingPill {
                background-color: #4f46e5;
                color: #ffffff;
                border: 1px solid #6366f1;
                border-radius: 14px;
                padding: 5px 14px;
                font-family: Inter, system-ui, sans-serif;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton#FloatingPill:hover {
                background-color: #4338ca;
            }
        """)
        self.floating_pill.hide()
        self.floating_pill.clicked.connect(self.jump_to_bottom)

        layout.addWidget(self.canvas_container, 1)

        # 4. Footer Bar
        footer = self._build_footer()
        layout.addWidget(footer)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("LogStreamPaneHeader")
        header.setFixedHeight(38)
        header.setStyleSheet("""
            QFrame#LogStreamPaneHeader {
                background-color: #14141e;
                border-top-left-radius: 9px;
                border-top-right-radius: 9px;
                border-bottom: 1px solid #1f1f2e;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 0, 10, 0)
        h_layout.setSpacing(8)

        # Status Dot
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #10b981; font-size: 11px;")
        h_layout.addWidget(self.status_dot)

        # Stream Name
        self.title_label = QLabel(self.config.name)
        self.title_label.setStyleSheet("color: #f4f4f5; font-size: 12px; font-weight: bold;")
        h_layout.addWidget(self.title_label)

        # File Path Badge
        path_text = self.config.target_path if self.config.source_type == "file" else f"journalctl -u {self.config.unit_name}"
        self.path_badge = QLabel(path_text)
        self.path_badge.setStyleSheet("""
            background-color: #0c0c11;
            color: #a1a1aa;
            border: 1px solid #232334;
            border-radius: 4px;
            padding: 2px 7px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
        """)
        h_layout.addWidget(self.path_badge)

        # Velocity Tag
        self.velocity_badge = QLabel("0.0 l/s")
        self.velocity_badge.setStyleSheet("""
            background-color: rgba(16, 185, 129, 0.12);
            color: #34d399;
            border-radius: 4px;
            padding: 2px 6px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            font-weight: 600;
        """)
        h_layout.addWidget(self.velocity_badge)

        h_layout.addStretch()

        # Header Action Buttons
        self.pause_btn = QPushButton("❚❚ Pause")
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.setFixedHeight(24)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a26;
                color: #e4e4e7;
                border: 1px solid #272738;
                border-radius: 5px;
                padding: 0 9px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10.5px;
            }
            QPushButton:hover {
                background-color: #27273a;
                color: #ffffff;
            }
        """)
        self.pause_btn.clicked.connect(self._toggle_pause)
        h_layout.addWidget(self.pause_btn)

        self.wrap_btn = QPushButton("Wrap")
        self.wrap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wrap_btn.setFixedHeight(24)
        self.wrap_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a26;
                color: #a1a1aa;
                border: 1px solid #272738;
                border-radius: 5px;
                padding: 0 8px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10.5px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.wrap_btn.clicked.connect(self._toggle_wrap)
        h_layout.addWidget(self.wrap_btn)

        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setFixedHeight(24)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a26;
                color: #a1a1aa;
                border: 1px solid #272738;
                border-radius: 5px;
                padding: 0 8px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10.5px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        h_layout.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setFixedHeight(24)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a26;
                color: #a1a1aa;
                border: 1px solid #272738;
                border-radius: 5px;
                padding: 0 8px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10.5px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.clear_btn.clicked.connect(self.clear_buffer)
        h_layout.addWidget(self.clear_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #71717a;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #272738;
                color: #ef4444;
            }
        """)
        self.close_btn.clicked.connect(lambda: self.close_requested.emit(self.stream_id))
        h_layout.addWidget(self.close_btn)

        return header

    def _build_filter_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setObjectName("LogStreamPaneToolbar")
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet("""
            QFrame#LogStreamPaneToolbar {
                background-color: #0d0d13;
                border-bottom: 1px solid #1a1a26;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(10, 0, 10, 0)
        t_layout.setSpacing(6)

        # Search Input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter regex or keyword (e.g. 500, /api/v1, POST)...")
        self.search_input.setFixedHeight(26)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #14141e;
                color: #f4f4f5;
                border: 1px solid #232334;
                border-radius: 5px;
                padding: 0 8px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid #6366f1;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        t_layout.addWidget(self.search_input, 1)

        # Mode Toggles: Regex, Case, Invert
        self.regex_toggle = QPushButton(".*")
        self.regex_toggle.setCheckable(True)
        self.regex_toggle.setToolTip("Enable Regular Expression search")
        self.regex_toggle.setFixedSize(28, 24)
        self.regex_toggle.setStyleSheet(self._toggle_btn_style())
        self.regex_toggle.toggled.connect(self._on_mode_toggled)
        t_layout.addWidget(self.regex_toggle)

        self.case_toggle = QPushButton("Aa")
        self.case_toggle.setCheckable(True)
        self.case_toggle.setToolTip("Case Sensitive")
        self.case_toggle.setFixedSize(28, 24)
        self.case_toggle.setStyleSheet(self._toggle_btn_style())
        self.case_toggle.toggled.connect(self._on_mode_toggled)
        t_layout.addWidget(self.case_toggle)

        self.invert_toggle = QPushButton("NOT")
        self.invert_toggle.setCheckable(True)
        self.invert_toggle.setToolTip("Invert Match (exclude matching lines)")
        self.invert_toggle.setFixedSize(38, 24)
        self.invert_toggle.setStyleSheet(self._toggle_btn_style())
        self.invert_toggle.toggled.connect(self._on_mode_toggled)
        t_layout.addWidget(self.invert_toggle)

        # Level Filter Chips
        self.chip_all = self._create_chip("ALL", "all", active=True)
        self.chip_errors = self._create_chip("ERRORS", "error", color="#f43f5e")
        self.chip_warns = self._create_chip("WARNS", "warn", color="#fbbf24")
        self.chip_success = self._create_chip("2xx OK", "2xx", color="#34d399")

        t_layout.addWidget(self.chip_all)
        t_layout.addWidget(self.chip_errors)
        t_layout.addWidget(self.chip_warns)
        t_layout.addWidget(self.chip_success)

        return toolbar

    def _create_chip(self, label: str, level: str, color: str = "#a1a1aa", active: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(24)
        btn.setProperty("level", level)
        self._update_chip_style(btn, active, color)
        btn.clicked.connect(lambda: self._select_level(level))
        return btn

    def _update_chip_style(self, btn: QPushButton, active: bool, color: str) -> None:
        if active:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #4f46e5;
                    color: #ffffff;
                    border: 1px solid #6366f1;
                    border-radius: 4px;
                    padding: 0 6px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10px;
                    font-weight: bold;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #14141e;
                    color: {color};
                    border: 1px solid #232334;
                    border-radius: 4px;
                    padding: 0 6px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: #1c1c2a;
                    border-color: #3b3b4f;
                }}
            """)

    def _toggle_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #14141e;
                color: #cbd5e1;
                border: 1px solid #2a2a3e;
                border-radius: 4px;
                padding: 0;
                font-family: Inter, system-ui, -apple-system, sans-serif;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #1f1f2f;
                color: #ffffff;
                border-color: #3f3f58;
            }
            QPushButton:checked {
                background-color: rgba(99, 102, 241, 0.25);
                color: #a5b4fc;
                border: 1px solid #6366f1;
            }
        """

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("LogStreamPaneFooter")
        footer.setFixedHeight(28)
        footer.setStyleSheet("""
            QFrame#LogStreamPaneFooter {
                background-color: #111116;
                border-bottom-left-radius: 9px;
                border-bottom-right-radius: 9px;
                border-top: 1px solid #1a1a26;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(12, 0, 12, 0)

        self.footer_lines = QLabel("Lines: 0 / 10,000 max")
        self.footer_lines.setStyleSheet("color: #94a3b8; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        f_layout.addWidget(self.footer_lines)

        f_layout.addStretch()

        self.footer_rate = QLabel("Rate: 0.0 l/s")
        self.footer_rate.setStyleSheet("color: #10b981; font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600;")
        f_layout.addWidget(self.footer_rate)

        encoding_label = QLabel("Encoding: UTF-8")
        encoding_label.setStyleSheet("color: #52525b; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        f_layout.addWidget(encoding_label)

        return footer

    def minimumSizeHint(self) -> QSize:
        return QSize(240, 160)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        w = self.width()

        # Responsive header controls
        if hasattr(self, "path_badge"):
            self.path_badge.setVisible(w >= 440)
        if hasattr(self, "velocity_badge"):
            self.velocity_badge.setVisible(w >= 390)
        if hasattr(self, "wrap_btn"):
            self.wrap_btn.setVisible(w >= 350)
        if hasattr(self, "copy_btn"):
            self.copy_btn.setVisible(w >= 320)

        # Responsive toolbar chips
        if hasattr(self, "chip_success"):
            self.chip_success.setVisible(w >= 380)
        if hasattr(self, "invert_toggle"):
            self.invert_toggle.setVisible(w >= 420)

        # Position floating pill at bottom-right inside canvas
        pill_w = min(340, max(180, w - 48))
        pill_h = 30
        x = self.canvas.width() - pill_w - 24
        y = self.canvas.height() - pill_h - 16
        self.floating_pill.setGeometry(max(10, x), max(10, y), pill_w, pill_h)

    def append_log_entry(self, entry: LogEntry) -> None:
        """Thread-safe enqueue of new LogEntry."""
        self._queue.put(entry)

    def _flush_batch_queue(self) -> None:
        """Drain queued entries in batch and append to document in one atomic edit block."""
        if self._queue.empty():
            return

        batch: list[LogEntry] = []
        while not self._queue.empty() and len(batch) < 300:
            batch.append(self._queue.get_nowait())

        if not batch:
            return

        self._all_entries.extend(batch)
        if len(self._all_entries) > 10000:
            self._all_entries = self._all_entries[-10000:]

        self._total_lines = len(self._all_entries)
        self.footer_lines.setText(f"Lines: {self._total_lines:,} / 10,000 max")

        # Filter batch against current search/level filters
        matching = [e for e in batch if self._entry_matches(e)]
        if not matching:
            return

        html_blocks: list[str] = []
        for entry in matching:
            html_blocks.append(self._format_entry_html(entry))

        combined_html = "".join(html_blocks)

        cursor = self.canvas.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        cursor.insertHtml(combined_html)
        cursor.endEditBlock()

        if self._auto_scroll:
            self.canvas.verticalScrollBar().setValue(self.canvas.verticalScrollBar().maximum())
        else:
            self._pending_new_lines += len(matching)
            self.floating_pill.setText(f"↓ Auto-scroll paused ({self._pending_new_lines} new lines) — Jump to bottom")
            self.floating_pill.show()
            self.floating_pill.raise_()

    def _format_entry_html(self, entry: LogEntry) -> str:
        line_num = f'<span style="color:#52525b; display:inline-block; width:36px;">{entry.line_number}</span> '

        if entry.status_code is not None and entry.client_ip:
            # Access Log Format
            status = entry.status_code
            status_style = "background-color:rgba(16,185,129,0.15); color:#34d399; font-weight:bold; border-radius:3px; padding:1px 4px;"
            if status >= 500:
                status_style = "background-color:rgba(244,63,94,0.2); color:#f43f5e; font-weight:bold; border-radius:3px; padding:1px 4px;"
            elif status >= 400:
                status_style = "background-color:rgba(251,191,36,0.2); color:#fbbf24; font-weight:bold; border-radius:3px; padding:1px 4px;"
            elif status == 304:
                status_style = "background-color:rgba(56,189,248,0.15); color:#38bdf8; font-weight:bold; border-radius:3px; padding:1px 4px;"

            return (
                f'<div style="margin:2px 0; white-space:nowrap;">'
                f'{line_num}'
                f'<span style="color:#71717a;">{html.escape(entry.timestamp)}</span> '
                f'<span style="color:#818cf8; font-weight:500;">{html.escape(entry.client_ip)}</span> '
                f'<span style="color:#38bdf8; font-weight:bold;">{html.escape(entry.method or "")}</span> '
                f'<span style="color:#f4f4f5;">{html.escape(entry.path or "")}</span> '
                f'<span style="{status_style}">{status}</span> '
                f'<span style="color:#a1a1aa;">{html.escape(entry.size or "")}</span> '
                f'<span style="color:#71717a;">{html.escape(entry.duration or "")}</span>'
                f'</div>'
            )

        if entry.level in ("error", "crit", "alert", "emerg", "warn"):
            # Error / Warning Log Format
            lvl_color = "#f43f5e" if entry.level != "warn" else "#fbbf24"
            lvl_badge = f'<span style="color:{lvl_color}; font-weight:bold;">[{entry.level.upper()}]</span>'
            pid_str = f'<span style="color:#71717a;">{html.escape(entry.pid)}:</span> ' if entry.pid else ""
            unit_str = f'<span style="color:#818cf8;">{html.escape(entry.unit)}:</span> ' if entry.unit else ""

            return (
                f'<div style="margin:2px 0; white-space:nowrap;">'
                f'{line_num}'
                f'<span style="color:#71717a;">{html.escape(entry.timestamp)}</span> '
                f'{lvl_badge} '
                f'{pid_str}'
                f'{unit_str}'
                f'<span style="color:#e4e4e7;">{html.escape(entry.text)}</span>'
                f'</div>'
            )

        # Standard / Default Format
        unit_str = f'<span style="color:#818cf8;">{html.escape(entry.unit)}:</span> ' if entry.unit else ""
        return (
            f'<div style="margin:2px 0; white-space:nowrap;">'
            f'{line_num}'
            f'<span style="color:#71717a;">{html.escape(entry.timestamp)}</span> '
            f'{unit_str}'
            f'<span style="color:#d4d4d8;">{html.escape(entry.text)}</span>'
            f'</div>'
        )

    def _entry_matches(self, entry: LogEntry) -> bool:
        # 1. Level filter check
        if self._level_filter == "error":
            if entry.level not in ("error", "crit", "alert", "emerg") and (entry.status_code is None or entry.status_code < 500):
                return False
        elif self._level_filter == "warn":
            if entry.level != "warn" and (entry.status_code is None or not (400 <= entry.status_code < 500)):
                return False
        elif self._level_filter == "2xx":
            if entry.status_code is None or not (200 <= entry.status_code < 300):
                return False

        # 2. Query filter check
        if not self._filter_query:
            return True

        text_to_search = entry.raw
        matches = False
        if self._regex_mode:
            try:
                flags = 0 if self._case_sensitive else re.IGNORECASE
                matches = bool(re.search(self._filter_query, text_to_search, flags))
            except re.error:
                matches = False
        else:
            q = self._filter_query if self._case_sensitive else self._filter_query.lower()
            target = text_to_search if self._case_sensitive else text_to_search.lower()
            matches = q in target

        return not matches if self._invert_mode else matches

    def _rebuild_canvas(self) -> None:
        """Full re-render of canvas from _all_entries when filter parameters change."""
        self.canvas.clear()
        matching = [e for e in self._all_entries if self._entry_matches(e)]
        if not matching:
            return

        html_blocks = [self._format_entry_html(e) for e in matching]
        cursor = self.canvas.textCursor()
        cursor.beginEditBlock()
        cursor.insertHtml("".join(html_blocks))
        cursor.endEditBlock()

        if self._auto_scroll:
            self.canvas.verticalScrollBar().setValue(self.canvas.verticalScrollBar().maximum())

    def _on_vertical_scroll(self, value: int) -> None:
        max_val = self.canvas.verticalScrollBar().maximum()
        is_at_bottom = value >= (max_val - 25)

        if is_at_bottom:
            self._auto_scroll = True
            self._pending_new_lines = 0
            self.floating_pill.hide()
        else:
            self._auto_scroll = False

    def jump_to_bottom(self) -> None:
        self._auto_scroll = True
        self._pending_new_lines = 0
        self.floating_pill.hide()
        self.canvas.verticalScrollBar().setValue(self.canvas.verticalScrollBar().maximum())

    def _toggle_pause(self) -> None:
        if self._status == LogStreamStatus.STREAMING:
            self.set_status(LogStreamStatus.PAUSED)
            self.pause_toggled.emit(self.stream_id, True)
        else:
            self.set_status(LogStreamStatus.STREAMING)
            self.pause_toggled.emit(self.stream_id, False)

    def _toggle_wrap(self) -> None:
        self._wrap = not self._wrap
        if self._wrap:
            self.canvas.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            self.wrap_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4f46e5;
                    color: #ffffff;
                    border: 1px solid #6366f1;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10.5px;
                    font-weight: bold;
                }
            """)
        else:
            self.canvas.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self.wrap_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1a1a26;
                    color: #a1a1aa;
                    border: 1px solid #272738;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10.5px;
                }
                QPushButton:hover {
                    color: #ffffff;
                }
            """)

    def _on_search_changed(self, text: str) -> None:
        self._filter_query = text.strip()
        self._rebuild_canvas()

    def _on_mode_toggled(self) -> None:
        self._regex_mode = self.regex_toggle.isChecked()
        self._case_sensitive = self.case_toggle.isChecked()
        self._invert_mode = self.invert_toggle.isChecked()
        self._rebuild_canvas()

    def _select_level(self, level: str) -> None:
        self._level_filter = level
        self._update_chip_style(self.chip_all, level == "all", "#a1a1aa")
        self._update_chip_style(self.chip_errors, level == "error", "#f43f5e")
        self._update_chip_style(self.chip_warns, level == "warn", "#fbbf24")
        self._update_chip_style(self.chip_success, level == "2xx", "#34d399")
        self._rebuild_canvas()

    def set_status(self, status: LogStreamStatus) -> None:
        self._status = status
        if status == LogStreamStatus.STREAMING:
            self.status_dot.setText("●")
            self.status_dot.setStyleSheet("color: #10b981; font-size: 11px;")
            self.pause_btn.setText("❚❚ Pause")
        elif status == LogStreamStatus.PAUSED:
            self.status_dot.setText("❚❚")
            self.status_dot.setStyleSheet("color: #f59e0b; font-size: 11px;")
            self.pause_btn.setText("▶ Resume")
        elif status == LogStreamStatus.ERROR:
            self.status_dot.setText("✕")
            self.status_dot.setStyleSheet("color: #ef4444; font-size: 11px;")
        else:
            self.status_dot.setText("●")
            self.status_dot.setStyleSheet("color: #71717a; font-size: 11px;")

    def update_velocity(self, vel: float) -> None:
        self._velocity = vel
        self.velocity_badge.setText(f"{vel:.1f} l/s")
        self.footer_rate.setText(f"Rate: {vel:.1f} l/s")

    def copy_to_clipboard(self) -> None:
        cursor = self.canvas.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", "\n")
        else:
            text = self.canvas.toPlainText()
        QApplication.clipboard().setText(text)

    def clear_buffer(self) -> None:
        self.canvas.clear()
        self._all_entries.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
        self._total_lines = 0
        self._pending_new_lines = 0
        self.floating_pill.hide()
        self.footer_lines.setText("Lines: 0 / 10,000 max")
        self.clear_requested.emit(self.stream_id)
