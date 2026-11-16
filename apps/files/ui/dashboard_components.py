from __future__ import annotations

from collections import deque
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.health_monitor import (
    DirectorySizeInfo,
    DiskMountInfo,
    ProcessInfo,
    format_bytes,
)
from ui.icons import get_icon


def hex_to_rgba(hex_str: str, alpha: float) -> str:
    """Convert hex string (#RGB or #RRGGBB) to valid Qt rgba(r, g, b, a) CSS."""
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) >= 6:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha:.2f})"
    return hex_str


class SparklineWidget(QWidget):
    """
    High-performance smooth vector sparkline widget with a subtle vertical gradient fill.
    Maintains a rolling ring buffer of values.
    """

    def __init__(
        self,
        line_color: str = "#6366f1",
        max_points: int = 30,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._line_color = QColor(line_color)
        self._max_points = max(5, max_points)
        self._history: deque[float] = deque(maxlen=self._max_points)
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def add_value(self, val: float) -> None:
        self._history.append(float(val))
        self.update()

    def set_values(self, values: list[float]) -> None:
        self._history.clear()
        for v in values[-self._max_points :]:
            self._history.append(float(v))
        self.update()

    def clear(self) -> None:
        self._history.clear()
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())

        # Elevated surface & crisp subtle border
        bg_rect = QRectF(0, 0, w, h)
        painter.setPen(QPen(QColor("#1f1f28"), 1))
        painter.setBrush(QBrush(QColor("#0f0f14")))
        painter.drawRoundedRect(bg_rect, 6, 6)

        n = len(self._history)
        if n < 2:
            # Draw placeholder baseline
            painter.setPen(QPen(QColor("#2d2d3a"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(6, h / 2), QPointF(w - 6, h / 2))
            painter.end()
            return

        min_val = min(self._history)
        max_val = max(self._history)
        val_range = max(1.0, max_val - min_val)

        # Calculate coordinates
        padding_top = 4.0
        padding_bottom = 4.0
        usable_h = h - padding_top - padding_bottom
        dx = (w - 12.0) / float(n - 1)

        points: list[QPointF] = []
        for i, val in enumerate(self._history):
            x = 6.0 + i * dx
            norm = (val - min_val) / val_range
            y = (h - padding_bottom) - (norm * usable_h)
            points.append(QPointF(x, y))

        # Build line path
        line_path = QPainterPath()
        line_path.moveTo(points[0])
        for pt in points[1:]:
            line_path.lineTo(pt)

        # Build area path for gradient
        area_path = QPainterPath(line_path)
        area_path.lineTo(points[-1].x(), h)
        area_path.lineTo(points[0].x(), h)
        area_path.closeSubpath()

        # Gradient fill
        gradient = QLinearGradient(0, 0, 0, h)
        top_color = QColor(self._line_color)
        top_color.setAlpha(90)
        bot_color = QColor(self._line_color)
        bot_color.setAlpha(0)
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, bot_color)

        painter.fillPath(area_path, QBrush(gradient))

        # Line stroke
        pen = QPen(self._line_color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(line_path)

        painter.end()


class MetricCardWidget(QFrame):
    """
    Card display widget for high-level KPIs (CPU, RAM, Disk, Net).
    Follows Raycast / Linear aesthetics with elevated surface and high-contrast typography.
    """

    def __init__(
        self,
        title: str,
        icon_name: str,
        accent_color: str = "#6366f1",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setStyleSheet(
            """
            QFrame#MetricCard {
                background-color: #15151c;
                border: 1px solid #242430;
                border-radius: 12px;
            }
            QFrame#MetricCard:hover {
                border-color: #383848;
            }
            """
        )
        self._accent_color = accent_color
        icon_bg = hex_to_rgba(accent_color, 0.15)
        icon_border = hex_to_rgba(accent_color, 0.35)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header Row: Icon + Title on left, Badge on right
        header = QHBoxLayout()
        header.setSpacing(8)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(24, 24)
        pix = get_icon(icon_name).pixmap(16, 16)
        self.icon_label.setPixmap(pix)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet(
            f"background-color: {icon_bg}; border-radius: 6px; border: 1px solid {icon_border};"
        )
        header.addWidget(self.icon_label)

        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #cbd5e1; letter-spacing: 0.5px; background: transparent;"
        )
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.badge_label = QLabel("")
        self.badge_label.setStyleSheet(
            "background-color: #1e1e28; border: 1px solid #2d2d3d; border-radius: 5px; "
            "padding: 2px 7px; font-size: 10px; font-family: monospace; font-weight: 600; color: #cbd5e1;"
        )
        header.addWidget(self.badge_label)
        layout.addLayout(header)

        # Metric Main Row: Large tabular value + secondary info
        val_row = QHBoxLayout()
        val_row.setSpacing(6)
        self.val_label = QLabel("0.0%")
        self.val_label.setStyleSheet(
            "font-size: 24px; font-weight: 800; font-family: monospace; color: #ffffff; background: transparent;"
        )
        val_row.addWidget(self.val_label)

        self.sub_val_label = QLabel("")
        self.sub_val_label.setStyleSheet(
            "font-size: 11px; font-family: monospace; color: #cbd5e1; font-weight: 500; background: transparent;"
        )
        val_row.addWidget(self.sub_val_label)
        val_row.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #34d399; background: transparent;"
        )
        val_row.addWidget(self.status_label)
        layout.addLayout(val_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: #1e1e28;
                border: 1px solid #2b2b3a;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_color};
                border-radius: 2px;
            }}
            """
        )
        layout.addWidget(self.progress_bar)

        # Vector Sparkline
        self.sparkline = SparklineWidget(line_color=accent_color, max_points=35)
        layout.addWidget(self.sparkline)

        # Footer Row: Detailed sub-metrics with clear contrast
        self.footer_label = QLabel("")
        self.footer_label.setStyleSheet(
            "font-size: 10px; font-family: monospace; color: #94a3b8; font-weight: 500; "
            "border-top: 1px solid #23232f; padding-top: 8px; background: transparent;"
        )
        layout.addWidget(self.footer_label)

    def set_data(
        self,
        value: str,
        sub_value: str = "",
        status: str = "",
        status_color: str = "#34d399",
        percent: float = 0.0,
        badge: str = "",
        footer: str = "",
        spark_val: float | None = None,
    ) -> None:
        self.val_label.setText(value)
        self.sub_val_label.setText(sub_value)
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {status_color}; background: transparent;")
        if badge:
            self.badge_label.setText(badge)
            self.badge_label.setVisible(True)
        else:
            self.badge_label.setVisible(False)
        self.progress_bar.setValue(int(max(0, min(100, percent))))
        self.footer_label.setText(footer)
        if spark_val is not None:
            self.sparkline.add_value(spark_val)


class ProcessKillDialog(QDialog):
    """
    Confirmation dialog for terminating remote processes with graceful SIGTERM
    or forced SIGKILL options.
    """

    def __init__(self, pid: int, command: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Terminate Remote Process")
        self.setFixedSize(440, 240)
        self.setModal(True)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #15151c;
                border: 1px solid #2b2b3a;
                border-radius: 12px;
            }
            QLabel {
                color: #f4f4f5;
                background: transparent;
            }
            QRadioButton {
                color: #e2e8f0;
                font-size: 12px;
                spacing: 8px;
                background: transparent;
            }
            QRadioButton::indicator {
                width: 14px;
                height: 14px;
            }
            QPushButton {
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel(f"Terminate PID {pid}?")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f43f5e; background: transparent;")
        layout.addWidget(title)

        msg = QLabel(
            f"Are you sure you want to stop process:\n<b style='color:#ffffff; font-family: monospace;'>{command}</b>?"
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 12px; color: #cbd5e1; background: transparent;")
        layout.addWidget(msg)

        # Radio options
        self.radio_sigterm = QRadioButton("Graceful Termination (SIGTERM - 15)")
        self.radio_sigterm.setChecked(True)
        layout.addWidget(self.radio_sigterm)

        self.radio_sigkill = QRadioButton("Force Kill immediately (SIGKILL - 9)")
        layout.addWidget(self.radio_sigkill)

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "background-color: #20202a; color: #cbd5e1; border: 1px solid #2d2d3d;"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        kill_btn = QPushButton("Kill Process")
        kill_btn.setStyleSheet(
            "background-color: #e11d48; color: #ffffff; border: none; font-weight: 700;"
        )
        kill_btn.clicked.connect(self.accept)
        btn_row.addWidget(kill_btn)

        layout.addLayout(btn_row)

    @property
    def force(self) -> bool:
        return self.radio_sigkill.isChecked()


class ProcessTableWidget(QFrame):
    """
    Searchable, sortable process explorer table matching Linear/Raycast UI.
    """

    kill_requested = Signal(int, str, bool)  # pid, command, force

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProcessCard")
        self.setStyleSheet(
            """
            QFrame#ProcessCard {
                background-color: #15151c;
                border: 1px solid #242430;
                border-radius: 12px;
            }
            """
        )
        self._raw_processes: tuple[ProcessInfo, ...] = ()
        self._sort_key = "cpu"
        self._sort_reverse = True
        self._search_query = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(10)

        title_box = QHBoxLayout()
        title_box.setSpacing(8)
        title_lbl = QLabel("ACTIVE PROCESSES")
        title_lbl.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #cbd5e1; letter-spacing: 0.5px; background: transparent;"
        )
        title_box.addWidget(title_lbl)

        self.count_badge = QLabel("0 Total")
        self.count_badge.setStyleSheet(
            "background-color: #1e1e28; border: 1px solid #2d2d3d; border-radius: 5px; "
            "padding: 2px 7px; font-size: 10px; font-family: monospace; font-weight: 600; color: #94a3b8;"
        )
        title_box.addWidget(self.count_badge)
        header.addLayout(title_box)

        header.addStretch(1)

        # Search box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter name, PID, user...")
        self.search_input.setFixedWidth(220)
        self.search_input.setStyleSheet(
            """
            QLineEdit {
                background-color: #101014;
                border: 1px solid #2b2b3a;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #6366f1;
            }
            """
        )
        self.search_input.textChanged.connect(self._on_search_changed)
        header.addWidget(self.search_input)

        # Sort Buttons Group
        sort_box = QHBoxLayout()
        sort_box.setSpacing(3)
        self.sort_group = QButtonGroup(self)

        self.sort_cpu_btn = QPushButton("CPU %")
        self.sort_mem_btn = QPushButton("MEM %")
        self.sort_pid_btn = QPushButton("PID")

        for idx, btn in enumerate((self.sort_cpu_btn, self.sort_mem_btn, self.sort_pid_btn)):
            btn.setCheckable(True)
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #1b1b24;
                    border: 1px solid #2b2b3a;
                    color: #94a3b8;
                    border-radius: 5px;
                    padding: 3px 9px;
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
            self.sort_group.addButton(btn, idx)
            sort_box.addWidget(btn)

        self.sort_cpu_btn.setChecked(True)
        self.sort_group.idClicked.connect(self._on_sort_clicked)
        header.addLayout(sort_box)

        layout.addLayout(header)

        # Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "PID", "USER", "COMMAND", "CPU %", "MEM % (RSS)", "STATUS", "ACTIONS"
        ])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
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
        layout.addWidget(self.table)

    def set_processes(self, procs: tuple[ProcessInfo, ...]) -> None:
        self._raw_processes = procs
        self._apply_filter_and_render()

    def _on_search_changed(self, text: str) -> None:
        self._search_query = text.strip().lower()
        self._apply_filter_and_render()

    def _on_sort_clicked(self, btn_id: int) -> None:
        keys = ["cpu", "mem", "pid"]
        self._sort_key = keys[btn_id] if 0 <= btn_id < len(keys) else "cpu"
        self._sort_reverse = self._sort_key != "pid"
        self._apply_filter_and_render()

    def _apply_filter_and_render(self) -> None:
        filtered: list[ProcessInfo] = []
        for p in self._raw_processes:
            if self._search_query:
                combined = f"{p.pid} {p.user} {p.command}".lower()
                if self._search_query not in combined:
                    continue
            filtered.append(p)

        # Sort
        if self._sort_key == "cpu":
            filtered.sort(key=lambda x: x.cpu_percent, reverse=self._sort_reverse)
        elif self._sort_key == "mem":
            filtered.sort(key=lambda x: x.mem_percent, reverse=self._sort_reverse)
        elif self._sort_key == "pid":
            filtered.sort(key=lambda x: x.pid, reverse=self._sort_reverse)

        self.count_badge.setText(f"{len(self._raw_processes)} Total")
        self.table.setRowCount(len(filtered))

        for row, p in enumerate(filtered):
            # PID - clearly readable light slate
            item_pid = QTableWidgetItem(str(p.pid))
            item_pid.setForeground(QColor("#cbd5e1"))
            self.table.setItem(row, 0, item_pid)

            # USER - sky blue for users, bright purple for root
            item_user = QTableWidgetItem(p.user)
            user_color = "#38bdf8" if p.user != "root" else "#c084fc"
            item_user.setForeground(QColor(user_color))
            self.table.setItem(row, 1, item_user)

            # COMMAND - pure crisp white
            item_cmd = QTableWidgetItem(p.command)
            item_cmd.setForeground(QColor("#ffffff"))
            self.table.setItem(row, 2, item_cmd)

            # CPU %
            item_cpu = QTableWidgetItem(f"{p.cpu_percent:.1f}%")
            cpu_color = "#34d399" if p.cpu_percent < 15.0 else ("#f59e0b" if p.cpu_percent < 50.0 else "#ef4444")
            item_cpu.setForeground(QColor(cpu_color))
            item_cpu.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, item_cpu)

            # MEM %
            rss_formatted = format_bytes(p.mem_rss_bytes)
            item_mem = QTableWidgetItem(f"{p.mem_percent:.1f}% ({rss_formatted})")
            item_mem.setForeground(QColor("#e2e8f0"))
            item_mem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, item_mem)

            # STATUS - Running (green), Sleep (clean muted)
            item_stat = QTableWidgetItem(p.status)
            stat_color = "#34d399" if p.status == "Running" else "#94a3b8"
            item_stat.setForeground(QColor(stat_color))
            item_stat.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 5, item_stat)

            # KILL ACTION BUTTON - explicit red styling (NO green fallback)
            kill_btn = QPushButton("Kill")
            kill_btn.setObjectName("DangerButton")
            kill_btn.setFixedSize(50, 22)
            kill_btn.setStyleSheet(
                """
                QPushButton, QPushButton#DangerButton {
                    background-color: rgba(239, 68, 68, 0.15) !important;
                    color: #f87171 !important;
                    border: 1px solid rgba(239, 68, 68, 0.35) !important;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: 700;
                    font-family: system-ui, sans-serif;
                }
                QPushButton:hover, QPushButton#DangerButton:hover {
                    background-color: #ef4444 !important;
                    color: #ffffff !important;
                    border: 1px solid #ef4444 !important;
                }
                """
            )
            # Capture variables in closure
            kill_btn.clicked.connect(
                (lambda pid=p.pid, cmd=p.command: lambda: self._on_kill_clicked(pid, cmd))()
            )
            self.table.setCellWidget(row, 6, kill_btn)

    def _on_kill_clicked(self, pid: int, cmd: str) -> None:
        dlg = ProcessKillDialog(pid, cmd, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.kill_requested.emit(pid, cmd, dlg.force)


class DiskMountsWidget(QFrame):
    """
    Displays list of mounted POSIX filesystems with capacity progress bars.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DiskMountsWidget")
        self.setStyleSheet(
            """
            QFrame#DiskMountsWidget {
                background-color: #15151c;
                border: 1px solid #242430;
                border-radius: 12px;
            }
            """
        )
        self.layout_mounts = QVBoxLayout(self)
        self.layout_mounts.setContentsMargins(14, 14, 14, 14)
        self.layout_mounts.setSpacing(10)

        # Title
        hdr = QHBoxLayout()
        title = QLabel("MOUNTED FILESYSTEMS")
        title.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #cbd5e1; letter-spacing: 0.5px; background: transparent;"
        )
        hdr.addWidget(title)
        hdr.addStretch(1)
        sub = QLabel("POSIX df")
        sub.setStyleSheet("font-size: 10px; font-family: monospace; color: #94a3b8; background: transparent;")
        hdr.addWidget(sub)
        self.layout_mounts.addLayout(hdr)

        self.items_container = QVBoxLayout()
        self.items_container.setSpacing(8)
        self.layout_mounts.addLayout(self.items_container)
        self.layout_mounts.addStretch(1)

    def set_mounts(self, mounts: tuple[DiskMountInfo, ...]) -> None:
        # Clear existing
        while self.items_container.count():
            item = self.items_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        for m in mounts:
            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            row_l = QVBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(3)

            top = QHBoxLayout()
            pt_lbl = QLabel(m.mount_point)
            pt_lbl.setStyleSheet(
                "font-size: 11px; font-weight: 700; font-family: monospace; color: #ffffff; background: transparent;"
            )
            top.addWidget(pt_lbl)
            top.addStretch(1)

            used_str = format_bytes(m.used_bytes)
            tot_str = format_bytes(m.total_bytes)
            pct_color = "#34d399" if m.use_percent < 75.0 else ("#f59e0b" if m.use_percent < 90.0 else "#ef4444")
            detail_lbl = QLabel(f"{used_str} / {tot_str} <b style='color:{pct_color};'>({m.use_percent:.0f}%)</b>")
            detail_lbl.setStyleSheet(
                "font-size: 10px; font-family: monospace; color: #cbd5e1; background: transparent;"
            )
            top.addWidget(detail_lbl)
            row_l.addLayout(top)

            bar = QProgressBar()
            bar.setFixedHeight(5)
            bar.setTextVisible(False)
            bar.setValue(int(max(0, min(100, m.use_percent))))
            bar.setStyleSheet(
                f"""
                QProgressBar {{
                    background-color: #1e1e28;
                    border: 1px solid #2b2b3a;
                    border-radius: 2px;
                }}
                QProgressBar::chunk {{
                    background-color: {pct_color};
                    border-radius: 2px;
                }}
                """
            )
            row_l.addWidget(bar)
            self.items_container.addWidget(row_w)
            row_w.show()


class DiskSpaceConsumersWidget(QFrame):
    """
    Displays large disk consumers with on-demand 'Scan Now' button.
    """

    scan_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DiskConsumersWidget")
        self.setStyleSheet(
            """
            QFrame#DiskConsumersWidget {
                background-color: #15151c;
                border: 1px solid #242430;
                border-radius: 12px;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        v = QVBoxLayout()
        v.setSpacing(1)
        title = QLabel("DISK SPACE CONSUMERS")
        title.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #cbd5e1; letter-spacing: 0.5px; background: transparent;"
        )
        v.addWidget(title)
        sub = QLabel("Large directories on filesystem")
        sub.setStyleSheet("font-size: 10px; color: #94a3b8; background: transparent;")
        v.addWidget(sub)
        hdr.addLayout(v)
        hdr.addStretch(1)

        self.scan_btn = QPushButton("Scan Now")
        self.scan_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e1e28;
                border: 1px solid #2d2d3d;
                color: #e2e8f0;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2b2b3a;
                color: #ffffff;
                border-color: #434358;
            }
            """
        )
        self.scan_btn.clicked.connect(self.scan_requested.emit)
        hdr.addWidget(self.scan_btn)
        layout.addLayout(hdr)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.scroll.setWidget(self.list_container)

        layout.addWidget(self.scroll, 1)

        # Initialize with placeholder
        self.set_directories(())

    def set_directories(self, items: tuple[DirectorySizeInfo, ...]) -> None:
        while self.list_layout.count():
            child = self.list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not items:
            placeholder_card = QFrame()
            placeholder_card.setObjectName("PlaceholderCard")
            placeholder_card.setStyleSheet(
                """
                QFrame#PlaceholderCard {
                    background-color: #101015;
                    border: 1px dashed #282836;
                    border-radius: 8px;
                    padding: 16px;
                }
                """
            )
            p_layout = QVBoxLayout(placeholder_card)
            p_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            p_layout.setSpacing(6)

            p_icon = QLabel("📁")
            p_icon.setStyleSheet("font-size: 22px; background: transparent; border: none; padding: 0;")
            p_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            p_layout.addWidget(p_icon)

            p_title = QLabel("No Storage Audit Run Yet")
            p_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #f4f4f5; background: transparent; border: none; padding: 0;")
            p_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            p_layout.addWidget(p_title)

            p_msg = QLabel("Click 'Scan Now' to inspect /var and /home for top storage consumers.")
            p_msg.setWordWrap(True)
            p_msg.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none; padding: 0;")
            p_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            p_layout.addWidget(p_msg)

            self.list_layout.addWidget(placeholder_card)
            placeholder_card.show()
            self.list_layout.addStretch(1)
            return

        for it in items:
            card = QFrame()
            card.setObjectName("DirItemCard")
            card.setStyleSheet(
                """
                QFrame#DirItemCard {
                    background-color: #101015;
                    border: 1px solid #22222d;
                    border-radius: 8px;
                }
                QFrame#DirItemCard:hover {
                    border-color: #343444;
                    background-color: #14141b;
                }
                """
            )
            card_l = QHBoxLayout(card)
            card_l.setContentsMargins(10, 8, 10, 8)
            card_l.setSpacing(10)

            icon = QLabel("📁")
            icon.setStyleSheet("font-size: 16px; background: transparent; border: none; padding: 0;")
            card_l.addWidget(icon)

            text_box = QVBoxLayout()
            text_box.setSpacing(2)
            path_lbl = QLabel(it.path)
            path_lbl.setStyleSheet(
                "font-size: 11px; font-weight: 700; font-family: monospace; color: #ffffff; background: transparent; border: none; padding: 0;"
            )
            text_box.addWidget(path_lbl)
            desc_lbl = QLabel(it.description)
            desc_lbl.setStyleSheet("font-size: 10px; color: #94a3b8; background: transparent; border: none; padding: 0;")
            text_box.addWidget(desc_lbl)
            card_l.addLayout(text_box, 1)

            size_badge = QLabel(it.size_formatted)
            size_badge.setStyleSheet(
                "font-size: 11px; font-weight: 700; font-family: monospace; color: #fbbf24; "
                "background-color: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.28); "
                "border-radius: 5px; padding: 3px 8px;"
            )
            card_l.addWidget(size_badge)

            self.list_layout.addWidget(card)
            card.show()

        self.list_layout.addStretch(1)
