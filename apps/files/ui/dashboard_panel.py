from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.health_monitor import (
    TELEMETRY_SHELL_COMMAND,
    DirectorySizeInfo,
    ServerHealthCollector,
    ServerMetricsSnapshot,
    format_bytes,
    format_uptime,
    kill_remote_process,
    scan_remote_directory_sizes,
)
from core.result import OperationResult
from ui.async_worker import AsyncWorker
from ui.dashboard_components import (
    DiskMountsWidget,
    DiskSpaceConsumersWidget,
    MetricCardWidget,
    ProcessTableWidget,
    hex_to_rgba,
)
from ui.icons import get_icon


class DashboardHeader(QWidget):
    """Header toolbar for the Server Health & Resource Dashboard."""

    interval_changed = Signal(int)  # milliseconds
    pause_toggled = Signal(bool)  # is_paused
    refresh_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_paused = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(12)

        # Left: Icon + Title + Status + Meta
        left_box = QHBoxLayout()
        left_box.setSpacing(10)

        # Activity icon box
        icon_box = QLabel()
        icon_box.setFixedSize(32, 32)
        pix = get_icon("activity").pixmap(20, 20)
        icon_box.setPixmap(pix)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setStyleSheet(
            "background-color: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.35); border-radius: 8px;"
        )
        left_box.addWidget(icon_box)

        # Titles
        titles_box = QVBoxLayout()
        titles_box.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.title_label = QLabel("Server Health & Resource Monitor")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        top_row.addWidget(self.title_label)

        self.stream_badge = QLabel("● Live Stream (2s)")
        self.stream_badge.setStyleSheet(
            "background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 10px; "
            "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #34d399;"
        )
        top_row.addWidget(self.stream_badge)
        top_row.addStretch(1)
        titles_box.addLayout(top_row)

        self.meta_label = QLabel("No server connected")
        self.meta_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #cbd5e1; font-weight: 500;")
        titles_box.addWidget(self.meta_label)

        left_box.addLayout(titles_box)
        layout.addLayout(left_box)

        layout.addStretch(1)

        # Right Controls: Interval select, Pause, Refresh
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.interval_combo = QComboBox()
        self.interval_combo.addItem("1s (Real-time)", 1000)
        self.interval_combo.addItem("2s (Balanced)", 2000)
        self.interval_combo.addItem("5s (Eco)", 5000)
        self.interval_combo.setCurrentIndex(1)
        self.interval_combo.setStyleSheet(
            """
            QComboBox {
                background-color: #171720;
                border: 1px solid #2b2b3a;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
                color: #e2e8f0;
            }
            QComboBox:hover {
                border-color: #3b3b4f;
            }
            QComboBox:focus {
                border-color: #6366f1;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #171720;
                border: 1px solid #2b2b3a;
                color: #e2e8f0;
                selection-background-color: #2b2b3a;
            }
            """
        )
        self.interval_combo.currentIndexChanged.connect(self._on_interval_selected)
        controls.addWidget(self.interval_combo)

        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #171720;
                border: 1px solid #2b2b3a;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                color: #e2e8f0;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #232330;
                color: #ffffff;
                border-color: #3b3b4f;
            }
            """
        )
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        controls.addWidget(self.pause_btn)

        self.refresh_btn = QPushButton("🔄 Refresh Now")
        self.refresh_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #6366f1;
                border: none;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 11px;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            """
        )
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        controls.addWidget(self.refresh_btn)

        layout.addLayout(controls)

    def set_host_info(self, host_label: str, os_name: str, kernel: str, uptime_sec: float) -> None:
        uptime_str = format_uptime(uptime_sec) if uptime_sec > 0 else "Unknown"
        parts = [host_label]
        if os_name:
            parts.append(os_name)
        if kernel:
            parts.append(kernel)
        parts.append(f"Uptime: {uptime_str}")
        self.meta_label.setText(" • ".join(parts))

    def set_paused_state(self, paused: bool) -> None:
        self._is_paused = paused
        if paused:
            self.pause_btn.setText("▶ Resume")
            self.stream_badge.setText("⏸ Paused")
            self.stream_badge.setStyleSheet(
                "background-color: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 10px; "
                "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #fbbf24;"
            )
        else:
            self.pause_btn.setText("⏸ Pause")
            sec = self.interval_combo.currentData() // 1000
            self.stream_badge.setText(f"● Live Stream ({sec}s)")
            self.stream_badge.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 10px; "
                "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #34d399;"
            )

    def _on_interval_selected(self, index: int) -> None:
        ms = int(self.interval_combo.itemData(index))
        sec = ms // 1000
        if not self._is_paused:
            self.stream_badge.setText(f"● Live Stream ({sec}s)")
        self.interval_changed.emit(ms)

    def _on_pause_clicked(self) -> None:
        self.set_paused_state(not self._is_paused)
        self.pause_toggled.emit(self._is_paused)


class DashboardPanel(QWidget):
    """
    Main Server Health & Resource Dashboard Panel with live polling,
    KPI sparklines, process table, and storage analyzers.
    """

    connect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardPanel")
        self.setStyleSheet(
            """
            QWidget#DashboardPanel {
                background-color: #0c0c11;
            }
            """
        )

        self._collector = ServerHealthCollector()
        self._connection: Any | None = None
        self._profile: Any | None = None
        self._poll_interval_ms = 2000
        self._is_polling = False
        self._poll_worker: AsyncWorker | None = None
        self._kill_worker: AsyncWorker | None = None
        self._scan_worker: AsyncWorker | None = None
        self._has_scanned_dirs = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_telemetry)

        # Stack to switch between Live Dashboard and Disconnected Empty State
        self.stack = QStackedWidget(self)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.stack)

        self._build_empty_view()
        self._build_dashboard_view()

        self.stack.setCurrentIndex(0)  # Start in empty state

    def _build_empty_view(self) -> None:
        empty = QWidget()
        empty.setObjectName("EmptyView")
        empty.setStyleSheet("background: transparent;")
        l = QVBoxLayout(empty)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setSpacing(0)

        card = QFrame()
        card.setObjectName("EmptyStateCard")
        card.setFixedWidth(520)
        card.setStyleSheet(
            """
            QFrame#EmptyStateCard {
                background-color: #15151c;
                border: 1px solid #262634;
                border-radius: 16px;
            }
            """
        )
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(36, 36, 36, 36)
        card_l.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setObjectName("EmptyIcon")
        icon_lbl.setFixedSize(52, 52)
        pix = get_icon("activity").pixmap(30, 30)
        icon_lbl.setPixmap(pix)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            """
            QLabel#EmptyIcon {
                background-color: rgba(99, 102, 241, 0.15);
                border: 1px solid rgba(99, 102, 241, 0.35);
                border-radius: 14px;
            }
            """
        )
        card_l.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Server Health & Resource Monitor")
        title.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #ffffff; background: transparent; border: none; padding: 0;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_l.addWidget(title)

        desc = QLabel(
            "Connect to an SSH or SFTP host to inspect real-time CPU utilization, "
            "RAM consumption, active processes, and storage distribution agentlessly "
            "without installing anything on the remote host."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(
            "font-size: 13px; color: #94a3b8; background: transparent; border: none; padding: 0 16px;"
        )
        card_l.addWidget(desc)

        card_l.addSpacing(6)

        connect_btn = QPushButton("Go to Connections")
        connect_btn.setFixedSize(180, 38)
        connect_btn.setStyleSheet(
            """
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
            """
        )
        connect_btn.clicked.connect(self.connect_requested.emit)
        card_l.addWidget(connect_btn, 0, Qt.AlignmentFlag.AlignCenter)

        l.addWidget(card)
        self.stack.addWidget(empty)

    def _build_dashboard_view(self) -> None:
        dash = QWidget()
        dash.setObjectName("DashboardContentView")
        dash.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(dash)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 1. Header Toolbar
        self.header = DashboardHeader(self)
        self.header.interval_changed.connect(self._on_interval_changed)
        self.header.pause_toggled.connect(self._on_pause_toggled)
        self.header.refresh_clicked.connect(self._poll_telemetry)
        layout.addWidget(self.header)

        # 2. 4 Primary KPI Cards Grid
        kpi_grid = QHBoxLayout()
        kpi_grid.setSpacing(12)

        # Card 1: CPU
        self.card_cpu = MetricCardWidget(
            title="CPU Utilization",
            icon_name="activity",
            accent_color="#6366f1",
            parent=self,
        )
        kpi_grid.addWidget(self.card_cpu)

        # Card 2: Memory (RAM)
        self.card_mem = MetricCardWidget(
            title="Memory (RAM)",
            icon_name="folder",
            accent_color="#a855f7",
            parent=self,
        )
        kpi_grid.addWidget(self.card_mem)

        # Card 3: Root Disk
        self.card_disk = MetricCardWidget(
            title="Root Disk (/)",
            icon_name="files",
            accent_color="#10b981",
            parent=self,
        )
        kpi_grid.addWidget(self.card_disk)

        # Card 4: Network I/O
        self.card_net = MetricCardWidget(
            title="Network I/O",
            icon_name="connections",
            accent_color="#38bdf8",
            parent=self,
        )
        kpi_grid.addWidget(self.card_net)

        layout.addLayout(kpi_grid)

        # 3. Bottom Splitter (Processes Left 65%, Disks Right 35%)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setStyleSheet(
            """
            QSplitter::handle {
                background-color: #242430;
                width: 2px;
            }
            """
        )

        # Left: Process Table
        self.process_table = ProcessTableWidget(self)
        self.process_table.kill_requested.connect(self._on_kill_process_requested)
        self.splitter.addWidget(self.process_table)

        # Right: Mounts + Directory Sizes
        right_container = QWidget()
        right_container.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        self.mounts_widget = DiskMountsWidget(self)
        right_layout.addWidget(self.mounts_widget)

        self.consumers_widget = DiskSpaceConsumersWidget(self)
        self.consumers_widget.scan_requested.connect(self._on_scan_sizes_requested)
        right_layout.addWidget(self.consumers_widget, 1)

        self.splitter.addWidget(right_container)
        self.splitter.setStretchFactor(0, 65)
        self.splitter.setStretchFactor(1, 35)

        layout.addWidget(self.splitter, 1)

        self.stack.addWidget(dash)

    def set_connection(self, connection: Any | None, profile: Any | None = None) -> None:
        """Update active connection reference and restart/pause health telemetry stream."""
        self._connection = connection
        self._profile = profile
        self._collector.reset()
        self._has_scanned_dirs = False

        if connection is None:
            self._timer.stop()
            self.stack.setCurrentIndex(0)
            return

        # Prepare header with host information
        host_title = profile.name if profile and profile.name else (profile.host if profile else "Remote Server")
        user_host = f"{profile.username}@{profile.host}" if profile else "SSH"
        self.header.set_host_info(f"{host_title} ({user_host})", "", "", 0)

        self.stack.setCurrentIndex(1)
        self._timer.start(self._poll_interval_ms)
        self._poll_telemetry()

        # Automatically start a initial background scan for directory sizes
        self._on_scan_sizes_requested()

    def _on_interval_changed(self, interval_ms: int) -> None:
        self._poll_interval_ms = interval_ms
        if self._timer.isActive():
            self._timer.start(interval_ms)

    def _on_pause_toggled(self, is_paused: bool) -> None:
        if is_paused:
            self._timer.stop()
        else:
            if self._connection is not None:
                self._timer.start(self._poll_interval_ms)
                self._poll_telemetry()

    def _poll_telemetry(self) -> None:
        if self._connection is None or self._is_polling:
            return

        self._is_polling = True
        conn = self._connection

        def run_poll() -> Any:
            return conn.run_command(TELEMETRY_SHELL_COMMAND)

        self._poll_worker = AsyncWorker(run_poll)
        self._poll_worker.succeeded.connect(self._on_poll_success)
        self._poll_worker.failed.connect(self._on_poll_failed)
        self._poll_worker.start()

    def _on_poll_success(self, result: OperationResult) -> None:
        self._is_polling = False
        if not result.ok or not result.data:
            return

        stdout = result.data.get("stdout", "")
        if not stdout:
            return

        snapshot = self._collector.parse_batch(stdout)
        self._update_ui_with_snapshot(snapshot)

    def _on_poll_failed(self, error: Any) -> None:
        self._is_polling = False

    def _update_ui_with_snapshot(self, s: ServerMetricsSnapshot) -> None:
        # 1. Update Header metadata
        host_title = self._profile.name if self._profile and self._profile.name else (self._profile.host if self._profile else "Remote Server")
        user_host = f"{self._profile.username}@{self._profile.host}" if self._profile else "SSH"
        self.header.set_host_info(f"{host_title} ({user_host})", s.os_name, s.kernel_version, s.uptime_seconds)

        # 2. Update CPU Card
        cpu_status = "Normal" if s.cpu_percent < 70.0 else ("Elevated" if s.cpu_percent < 85.0 else "High")
        cpu_color = "#34d399" if s.cpu_percent < 70.0 else ("#f59e0b" if s.cpu_percent < 85.0 else "#ef4444")
        load_str = f"Load: {s.load_avg[0]:.2f} {s.load_avg[1]:.2f} {s.load_avg[2]:.2f}"
        self.card_cpu.set_data(
            value=f"{s.cpu_percent:.1f}%",
            sub_value=load_str,
            status=cpu_status,
            status_color=cpu_color,
            percent=s.cpu_percent,
            badge=f"{s.cpu_cores} Cores",
            footer=f"User: {s.cpu_user_percent:.1f}%   Sys: {s.cpu_sys_percent:.1f}%   I/O: {s.cpu_iowait_percent:.1f}%",
            spark_val=s.cpu_percent,
        )

        # 3. Update Memory Card
        mem_used_str = format_bytes(s.mem_used_bytes)
        mem_tot_str = format_bytes(s.mem_total_bytes)
        mem_pct = (s.mem_used_bytes / max(1, s.mem_total_bytes)) * 100.0
        mem_free_str = format_bytes(s.mem_available_bytes)
        swap_used_str = format_bytes(s.swap_used_bytes)
        self.card_mem.set_data(
            value=mem_used_str,
            sub_value=f"/ {mem_tot_str}",
            status=f"{mem_pct:.1f}%",
            status_color="#c084fc",
            percent=mem_pct,
            badge=f"{mem_free_str} Avail",
            footer=f"Swap: {swap_used_str}   Available: {mem_free_str}",
            spark_val=mem_pct,
        )

        # 4. Update Root Disk Card
        disk_used_str = format_bytes(s.disk_used_bytes)
        disk_tot_str = format_bytes(s.disk_total_bytes)
        disk_free_str = format_bytes(s.disk_free_bytes)
        self.card_disk.set_data(
            value=disk_used_str,
            sub_value=f"/ {disk_tot_str}",
            status=f"{s.disk_use_percent:.1f}%",
            status_color="#34d399" if s.disk_use_percent < 80.0 else "#ef4444",
            percent=s.disk_use_percent,
            badge="Root /",
            footer=f"Free: {disk_free_str}   Mounts: {len(s.mounts)} active",
            spark_val=s.disk_use_percent,
        )

        # 5. Update Network Card
        rx_speed = format_bytes(s.net_rx_rate_bytes_per_sec) + "/s"
        tx_speed = format_bytes(s.net_tx_rate_bytes_per_sec) + "/s"
        total_in = format_bytes(s.net_total_rx_bytes)
        total_out = format_bytes(s.net_total_tx_bytes)
        self.card_net.set_data(
            value=f"↓ {rx_speed}",
            sub_value=f"↑ {tx_speed}",
            status="Active",
            status_color="#38bdf8",
            percent=min(100.0, (s.net_rx_rate_bytes_per_sec / (125 * 1024 * 1024)) * 100.0),  # norm against 1Gbps
            badge=s.net_interface,
            footer=f"Total In: {total_in}   Total Out: {total_out}",
            spark_val=s.net_rx_rate_bytes_per_sec / 1024.0,  # KB/s
        )

        # 6. Update Process Table
        self.process_table.set_processes(s.processes)

        # 7. Update Mounts Table
        self.mounts_widget.set_mounts(s.mounts)

    def _on_kill_process_requested(self, pid: int, command: str, force: bool) -> None:
        if self._connection is None:
            return

        conn = self._connection

        def run_kill() -> Any:
            return kill_remote_process(conn, pid, force)

        self._kill_worker = AsyncWorker(run_kill)
        self._kill_worker.succeeded.connect(
            lambda res: self._on_kill_completed(res, pid)
        )
        self._kill_worker.failed.connect(
            lambda err: QMessageBox.warning(self, "Kill Failed", f"Could not kill PID {pid}: {err}")
        )
        self._kill_worker.start()

    def _on_kill_completed(self, result: OperationResult, pid: int) -> None:
        if result.ok:
            # Poll immediately to refresh table
            self._poll_telemetry()
        else:
            QMessageBox.warning(self, "Kill Process", result.message)

    def _on_scan_sizes_requested(self) -> None:
        if self._connection is None or (self._scan_worker and self._scan_worker.isRunning()):
            return

        self.consumers_widget.scan_btn.setEnabled(False)
        self.consumers_widget.scan_btn.setText("Scanning...")
        conn = self._connection

        def run_scan() -> Any:
            return scan_remote_directory_sizes(conn)

        self._scan_worker = AsyncWorker(run_scan)
        self._scan_worker.succeeded.connect(self._on_scan_completed)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_completed(self, items: tuple[DirectorySizeInfo, ...]) -> None:
        self._has_scanned_dirs = True
        self.consumers_widget.scan_btn.setEnabled(True)
        self.consumers_widget.scan_btn.setText("Scan Now")
        self.consumers_widget.set_directories(items)

    def _on_scan_failed(self, err: Any) -> None:
        self.consumers_widget.scan_btn.setEnabled(True)
        self.consumers_widget.scan_btn.setText("Scan Now")
        if not self._has_scanned_dirs:
            self.consumers_widget.set_directories(())
