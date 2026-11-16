from __future__ import annotations

import asyncio
import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.async_worker import AsyncRuntime, AsyncWorker
from core.health_monitor import format_bytes
from core.result import OperationResult
from core.tunnel_manager import (
    DEFAULT_TUNNEL_PRESETS,
    SSHTunnelManager,
    TunnelConfig,
    TunnelSessionInfo,
    TunnelStatus,
    TunnelType,
)
from ui.dashboard_components import SparklineWidget
from ui.icons import get_icon
from ui.tunnel_components import (
    NewTunnelModalDialog,
    TunnelCardWidget,
    TunnelDenseTableView,
    TunnelInspectorWidget,
)

logger = logging.getLogger("remote_file_manager.tunnels_panel")


class TunnelsHeaderToolbar(QWidget):
    """
    Header toolbar for the Tunnels & Port Forwarding panel.
    Matches Raycast / Linear design standards.
    """

    new_tunnel_clicked = Signal()
    refresh_clicked = Signal()
    view_changed = Signal(str)  # "split" or "table"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_mode = "split"
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(12)

        # Left box: Icon + Titles
        left_box = QHBoxLayout()
        left_box.setSpacing(10)

        icon_box = QLabel()
        icon_box.setFixedSize(32, 32)
        pix = get_icon("tunnels").pixmap(20, 20)
        icon_box.setPixmap(pix)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setStyleSheet(
            "background-color: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.35); border-radius: 8px;"
        )
        left_box.addWidget(icon_box)

        titles_box = QVBoxLayout()
        titles_box.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.title_label = QLabel("SSH Tunnels & Port Forwarding")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        top_row.addWidget(self.title_label)

        self.status_badge = QLabel("○ 0 Active")
        self.status_badge.setStyleSheet(
            "background-color: #1a1a24; border: 1px solid #2b2b3a; border-radius: 10px; "
            "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #94a3b8;"
        )
        top_row.addWidget(self.status_badge)
        top_row.addStretch(1)
        titles_box.addLayout(top_row)

        self.meta_label = QLabel("No server connected")
        self.meta_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #94a3b8;")
        titles_box.addWidget(self.meta_label)

        left_box.addLayout(titles_box)
        layout.addLayout(left_box)

        layout.addStretch(1)

        # Controls: View switcher, New Tunnel button, Refresh button
        controls = QHBoxLayout()
        controls.setSpacing(8)

        # Split vs Dense Table Switcher
        views_box = QHBoxLayout()
        views_box.setSpacing(0)
        views_box.setContentsMargins(0, 0, 0, 0)

        self.btn_split = QPushButton("Split View")
        self.btn_split.setCheckable(True)
        self.btn_split.setChecked(True)
        self.btn_split.setFixedSize(80, 28)
        self.btn_split.setStyleSheet(
            """
            QPushButton {
                background-color: #181824;
                border: 1px solid #2c2c3e;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                color: #94a3b8;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                color: #ffffff;
            }
            QPushButton:checked {
                background-color: #2c2c3e;
                color: #ffffff;
                border-color: #3f3f58;
            }
            """
        )
        self.btn_split.clicked.connect(lambda: self._on_view_mode_changed("split"))
        views_box.addWidget(self.btn_split)

        self.btn_table = QPushButton("Table View")
        self.btn_table.setCheckable(True)
        self.btn_table.setFixedSize(80, 28)
        self.btn_table.setStyleSheet(
            """
            QPushButton {
                background-color: #181824;
                border: 1px solid #2c2c3e;
                border-left: none;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                color: #94a3b8;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                color: #ffffff;
            }
            QPushButton:checked {
                background-color: #2c2c3e;
                color: #ffffff;
                border-color: #3f3f58;
            }
            """
        )
        self.btn_table.clicked.connect(lambda: self._on_view_mode_changed("table"))
        views_box.addWidget(self.btn_table)
        controls.addLayout(views_box)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedHeight(28)
        self.refresh_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #181824;
                border: 1px solid #2c2c3e;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                color: #e2e8f0;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #242436;
                color: #ffffff;
            }
            """
        )
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        controls.addWidget(self.refresh_btn)

        self.new_btn = QPushButton("+ New Tunnel")
        self.new_btn.setFixedHeight(28)
        self.new_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #6366f1;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-size: 11px;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            """
        )
        self.new_btn.clicked.connect(self.new_tunnel_clicked.emit)
        controls.addWidget(self.new_btn)

        layout.addLayout(controls)

    def set_host_info(self, host_label: str) -> None:
        self.meta_label.setText(host_label)

    def set_active_count(self, active: int, total: int) -> None:
        if active > 0:
            self.status_badge.setText(f"● {active} Active ({total} configured)")
            self.status_badge.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 10px; "
                "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #34d399;"
            )
        else:
            self.status_badge.setText(f"○ {total} Configured (Idle)")
            self.status_badge.setStyleSheet(
                "background-color: #1a1a24; border: 1px solid #2b2b3a; border-radius: 10px; "
                "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #94a3b8;"
            )

    def _on_view_mode_changed(self, mode: str) -> None:
        self._view_mode = mode
        self.btn_split.setChecked(mode == "split")
        self.btn_table.setChecked(mode == "table")
        self.view_changed.emit(mode)


class TunnelKPICard(QFrame):
    """
    Summary KPI card with value, subtitle, and optional sparkline.
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        value: str,
        sub: str,
        accent_color: str,
        sparkline: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TunnelKPICard")
        self._accent = accent_color
        self._has_sparkline = sparkline
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(84)
        self.setStyleSheet(
            f"""
            QFrame#TunnelKPICard {{
                background-color: #14141e;
                border: 1px solid #232332;
                border-radius: 10px;
                outline: none;
            }}
            QFrame#TunnelKPICard:hover {{
                border-color: #4f46e5;
                background-color: #171724;
            }}
            """
        )

        l = QVBoxLayout(self)
        l.setContentsMargins(14, 12, 14, 12)
        l.setSpacing(4)

        top_l = QHBoxLayout()
        top_l.setSpacing(6)
        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        top_l.addWidget(title_lbl)
        top_l.addStretch(1)

        if sparkline:
            self.spark = SparklineWidget(line_color=accent_color)
            self.spark.setFixedSize(54, 20)
            top_l.addWidget(self.spark)
        else:
            self.spark = None

        l.addLayout(top_l)

        self.val_lbl = QLabel(value)
        self.val_lbl.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {accent_color}; font-family: monospace;")
        l.addWidget(self.val_lbl)

        self.sub_lbl = QLabel(sub)
        self.sub_lbl.setStyleSheet("font-size: 11px; color: #71717a;")
        l.addWidget(self.sub_lbl)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_data(self, value: str, sub: str, spark_point: float | None = None, value_color: str | None = None) -> None:
        self.val_lbl.setText(value)
        self.sub_lbl.setText(sub)
        color = value_color or self._accent
        self.val_lbl.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {color}; font-family: monospace;")
        if self.spark and spark_point is not None:
            self.spark.add_value(spark_point)


class TunnelErrorDialog(QDialog):
    """
    Polished Raycast/Linear dark mode dialog for tunnel operational errors.
    Provides non-truncated, readable diagnostic output and 1-click automatic
    port reassignment for port collisions so users are never stuck.
    """

    def __init__(
        self,
        title: str,
        message: str,
        technical_details: str | None = None,
        suggested_port: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TunnelErrorDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedWidth(520)
        self.setStyleSheet(
            """
            QDialog#TunnelErrorDialog {
                background-color: #13131c;
            }
            """
        )
        self.suggested_port = suggested_port
        self.action_use_suggested = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        # 1. Header with Alert Badge
        hdr = QHBoxLayout()
        hdr.setSpacing(12)

        icon_box = QLabel()
        icon_box.setFixedSize(38, 38)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        is_collision = suggested_port is not None
        badge_bg = "rgba(245, 158, 11, 0.15)" if is_collision else "rgba(239, 68, 68, 0.15)"
        badge_border = "rgba(245, 158, 11, 0.35)" if is_collision else "rgba(239, 68, 68, 0.35)"
        icon_box.setStyleSheet(
            f"background-color: {badge_bg}; border: 1px solid {badge_border}; border-radius: 8px;"
        )
        icon_box.setPixmap(get_icon("alert").pixmap(20, 20))
        hdr.addWidget(icon_box)

        title_l = QVBoxLayout()
        title_l.setSpacing(2)
        heading = QLabel("Port Collision Detected" if is_collision else "Tunnel Operation Failed")
        heading.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        title_l.addWidget(heading)

        subheading = QLabel("Local endpoint conflict" if is_collision else "The requested operation could not complete")
        subheading.setStyleSheet("font-size: 11px; color: #94a3b8;")
        title_l.addWidget(subheading)
        hdr.addLayout(title_l)
        hdr.addStretch(1)
        layout.addLayout(hdr)

        # 2. Main Message Box
        msg_frame = QFrame()
        msg_frame.setObjectName("MsgFrame")
        msg_frame.setStyleSheet(
            """
            QFrame#MsgFrame {
                background-color: #171724;
                border: 1px solid #252536;
                border-radius: 8px;
            }
            """
        )
        msg_l = QVBoxLayout(msg_frame)
        msg_l.setContentsMargins(14, 12, 14, 12)
        msg_l.setSpacing(8)

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg_lbl.setStyleSheet("font-size: 12px; color: #e2e8f0; line-height: 1.4; border: none; background: transparent;")
        msg_l.addWidget(msg_lbl)

        if suggested_port is not None:
            tip_lbl = QLabel(
                f"Suggested solution: Switch to local port <b>{suggested_port}</b> which is verified open and ready on your machine."
            )
            tip_lbl.setWordWrap(True)
            tip_lbl.setStyleSheet("font-size: 11px; color: #38bdf8; border: none; background: transparent;")
            msg_l.addWidget(tip_lbl)

        if technical_details and not is_collision:
            details_lbl = QLabel(technical_details)
            details_lbl.setWordWrap(True)
            details_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details_lbl.setStyleSheet("font-family: monospace; font-size: 10px; color: #94a3b8; border: none; background: transparent;")
            msg_l.addWidget(details_lbl)

        layout.addWidget(msg_frame)

        # 3. Actions Row
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)

        cancel_btn = QPushButton("Cancel" if is_collision else "Close")
        cancel_btn.setStyleSheet(
            """
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
            """
        )
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)

        if is_collision:
            fix_btn = QPushButton(f"Switch to Port {suggested_port} and Start")
            fix_btn.setStyleSheet(
                """
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
                """
            )
            fix_btn.clicked.connect(self._on_fix_clicked)
            actions.addWidget(fix_btn)

        layout.addLayout(actions)

    def _on_fix_clicked(self) -> None:
        self.action_use_suggested = True
        self.accept()


class ConfirmDeleteTunnelDialog(QDialog):
    """
    Polished confirmation modal before deleting an SSH tunnel configuration.
    """

    def __init__(self, tunnel_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConfirmDeleteTunnelDialog")
        self.setWindowTitle("Delete Tunnel")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedWidth(440)
        self.setStyleSheet(
            """
            QDialog#ConfirmDeleteTunnelDialog {
                background-color: #13131c;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        icon_box = QLabel()
        icon_box.setFixedSize(34, 34)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setStyleSheet(
            "background-color: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 8px;"
        )
        icon_box.setPixmap(get_icon("trash").pixmap(18, 18))
        hdr.addWidget(icon_box)

        t_lbl = QLabel("Delete Tunnel Configuration?")
        t_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #ffffff;")
        hdr.addWidget(t_lbl)
        hdr.addStretch(1)
        layout.addLayout(hdr)

        desc = QLabel(
            f"Are you sure you want to remove the tunnel configuration '<b>{tunnel_name}</b>'? "
            "Any active forwarding on this port will be stopped."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px; color: #cbd5e1; line-height: 1.4;")
        layout.addWidget(desc)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            """
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
            """
        )
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)

        del_btn = QPushButton("Delete Tunnel")
        del_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #ef4444;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                padding: 6px 18px;
                font-weight: 700;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
            """
        )
        del_btn.clicked.connect(self.accept)
        actions.addWidget(del_btn)

        layout.addLayout(actions)


class TunnelsPanel(QWidget):
    """
    Main SSH Tunnels & Port Forwarding Panel.
    Pairs agentlessly with AsyncSSH client to open Local (-L), Remote (-R),
    and Dynamic SOCKS5 (-D) tunnels with zero remote agent dependencies.
    """

    connect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TunnelsPanel")
        self.setStyleSheet(
            """
            QWidget#TunnelsPanel {
                background-color: #0c0c11;
            }
            """
        )

        self._tunnel_mgr = SSHTunnelManager()
        self._connection: Any | None = None
        self._profile: Any | None = None
        self._tunnel_configs: list[TunnelConfig] = []
        self._selected_tunnel_id: str = ""
        self._active_type_filter: str = "all"
        self._search_query: str = ""
        self._workers: list[AsyncWorker] = []

        self._traffic_timer = QTimer(self)
        self._traffic_timer.setInterval(2000)
        self._traffic_timer.timeout.connect(self._on_traffic_tick)

        # Stack to switch between Live Panel and Disconnected Empty State
        self.stack = QStackedWidget(self)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.stack)

        self._build_empty_view()
        self._build_tunnels_view()

        self._init_default_configs()
        self.stack.setCurrentIndex(0)

    def _init_default_configs(self) -> None:
        for p in DEFAULT_TUNNEL_PRESETS:
            cfg = TunnelConfig(
                id=p["id"],
                name=p["name"],
                tunnel_type=p["tunnel_type"],
                local_host=p["local_host"],
                local_port=p["local_port"],
                remote_host=p["remote_host"],
                remote_port=p["remote_port"],
                description=p["description"],
                category=p["category"],
            )
            self._tunnel_configs.append(cfg)

    def _build_empty_view(self) -> None:
        empty = QWidget()
        empty.setObjectName("EmptyTunnelsView")
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
        pix = get_icon("tunnels").pixmap(30, 30)
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

        title = QLabel("SSH Tunnels & Port Forwarding")
        title.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #ffffff; background: transparent; border: none; padding: 0;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_l.addWidget(title)

        desc = QLabel(
            "Connect to an SSH host to securely forward local ports to remote databases, "
            "expose local web development servers to remote hosts, or create dynamic "
            "SOCKS5 application proxies agentlessly without installing anything on the remote host."
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

    def _build_tunnels_view(self) -> None:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 1. Header Toolbar
        self.header = TunnelsHeaderToolbar(self)
        self.header.new_tunnel_clicked.connect(self._open_new_tunnel_dialog)
        self.header.refresh_clicked.connect(self._render_tunnels)
        self.header.view_changed.connect(self._on_view_changed)
        layout.addWidget(self.header)

        # 2. KPI Summary Strip (4 Cards)
        kpi_bar = QHBoxLayout()
        kpi_bar.setSpacing(10)

        self.kpi_active = TunnelKPICard("Active Forwards", "0 Active", "0 of 6 running", "#34d399")
        self.kpi_active.clicked.connect(lambda: self._set_type_filter("active"))
        kpi_bar.addWidget(self.kpi_active)

        self.kpi_traffic = TunnelKPICard("Forwarded Traffic", "0.0 B/s", "Total: 0.0 MB", "#38bdf8", sparkline=True)
        kpi_bar.addWidget(self.kpi_traffic)

        self.kpi_latency = TunnelKPICard("Avg Socket Latency", "--", "Local loopback", "#a78bfa")
        kpi_bar.addWidget(self.kpi_latency)

        self.kpi_socks = TunnelKPICard("SOCKS5 Proxy", "Disabled", "Port 1080 Idle", "#f59e0b")
        self.kpi_socks.clicked.connect(lambda: self._set_type_filter("socks5"))
        kpi_bar.addWidget(self.kpi_socks)

        layout.addLayout(kpi_bar)

        # 3. Filter & Search Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # Type Filter chips
        self.chip_buttons: dict[str, QPushButton] = {}
        for f_key, f_label in (
            ("all", "All Tunnels"),
            ("active", "Active Only"),
            ("local", "Local (-L)"),
            ("remote", "Remote (-R)"),
            ("socks5", "SOCKS5 (-D)"),
        ):
            b = QPushButton(f_label)
            b.setCheckable(True)
            b.setFixedHeight(26)
            b.setStyleSheet(
                """
                QPushButton {
                    background-color: #181824;
                    border: 1px solid #28283a;
                    color: #94a3b8;
                    border-radius: 13px;
                    padding: 0 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    color: #e2e8f0;
                    border-color: #3b3b52;
                }
                QPushButton:checked {
                    background-color: #6366f1;
                    color: #ffffff;
                    border-color: #6366f1;
                }
                """
            )
            b.clicked.connect((lambda k=f_key: lambda: self._set_type_filter(k))())
            toolbar.addWidget(b)
            self.chip_buttons[f_key] = b

        self.chip_buttons["all"].setChecked(True)
        toolbar.addStretch(1)

        # Search Input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by name, port, or host...")
        self.search_input.setFixedWidth(240)
        self.search_input.setFixedHeight(28)
        self.search_input.setStyleSheet(
            """
            QLineEdit {
                background-color: #12121a;
                border: 1px solid #28283a;
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
        toolbar.addWidget(self.search_input)

        layout.addLayout(toolbar)

        # 4. Content Switcher: Split View vs Dense Table View
        self.view_stack = QStackedWidget(self)

        # Mode A: Split View (55% cards left, 45% inspector right)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setStyleSheet(
            """
            QSplitter {
                background: transparent;
                border: none;
            }
            QSplitter::handle {
                background-color: #1e1e2c;
                width: 1px;
            }
            """
        )

        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setMinimumWidth(380)
        cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if cards_scroll.viewport():
            cards_scroll.viewport().setStyleSheet("background: transparent; border: none; outline: none;")
        cards_scroll.setStyleSheet(
            """
            QScrollArea {
                background: transparent;
                border: none;
                outline: none;
            }
            QScrollArea:focus {
                border: none;
                outline: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #252538;
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3f3f58;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            """
        )

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 10, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch(1)

        cards_scroll.setWidget(self.cards_container)
        self.splitter.addWidget(cards_scroll)

        # Wrap inspector in scroll area for vertical responsiveness
        inspector_scroll = QScrollArea()
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inspector_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #252538;
                min-height: 20px;
                border-radius: 2px;
            }
        """)

        self.inspector = TunnelInspectorWidget()
        self.inspector.setMinimumWidth(320)
        self.inspector.toggle_requested.connect(self._on_tunnel_toggle)
        self.inspector.ping_requested.connect(self._on_tunnel_ping)
        inspector_scroll.setWidget(self.inspector)
        self.splitter.addWidget(inspector_scroll)

        self.splitter.setSizes([650, 450])
        self.splitter.setStretchFactor(0, 55)
        self.splitter.setStretchFactor(1, 45)
        self.view_stack.addWidget(self.splitter)

        # Mode B: Dense Table View
        self.dense_table = TunnelDenseTableView(self)
        self.dense_table.unit_selected.connect(self._select_tunnel)
        self.dense_table.toggle_requested.connect(self._on_tunnel_toggle)
        self.dense_table.delete_requested.connect(self._on_tunnel_delete)
        self.dense_table.ping_requested.connect(self._on_tunnel_ping)
        self.view_stack.addWidget(self.dense_table)

        layout.addWidget(self.view_stack, 1)
        self.stack.addWidget(view)

    def set_connection(self, connection: Any | None, profile: Any | None = None) -> None:
        """Update active connection reference and update status."""
        self._connection = connection
        self._profile = profile

        if connection is None:
            # Stop all active tunnels safely when disconnected
            self._traffic_timer.stop()
            self._close_all_active_tunnels()
            self.stack.setCurrentIndex(0)
            return

        host_title = profile.name if profile and profile.name else (profile.host if profile else "Remote Server")
        proto = getattr(profile, "protocol", "ssh") if profile else "ssh"
        user_host = f"{profile.username}@{profile.host}" if profile else "SSH"

        if proto not in ("ssh", "sftp"):
            self.header.set_host_info(f"{host_title} ({proto.upper()} - Port Forwarding Requires SSH)")
            self.header.status_badge.setText("⚠ SSH Required")
            self.header.status_badge.setStyleSheet(
                "background-color: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 10px; "
                "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #fbbf24;"
            )
        else:
            self.header.set_host_info(f"{host_title} ({user_host})")

        host = profile.host if profile else "example.com"
        user = profile.username if profile else "ubuntu"
        port = getattr(profile, "port", 22) or 22
        self.inspector.set_host_context(host, user, port)

        self.stack.setCurrentIndex(1)
        self._traffic_timer.start()
        self._render_tunnels()

    def _close_all_active_tunnels(self) -> None:
        try:
            AsyncRuntime.instance().submit(self._tunnel_mgr.stop_all_tunnels())
        except Exception as exc:
            logger.warning("Failed to submit stop_all_tunnels: %s", exc)

    def _track_worker(self, worker: AsyncWorker) -> None:
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _set_type_filter(self, filter_key: str) -> None:
        self._active_type_filter = filter_key
        for k, b in self.chip_buttons.items():
            b.setChecked(k == filter_key)
        self._render_tunnels()

    def _on_search_changed(self, text: str) -> None:
        self._search_query = text.strip().lower()
        self._render_tunnels()

    def _on_view_changed(self, mode: str) -> None:
        self.view_stack.setCurrentIndex(0 if mode == "split" else 1)

    def _get_filtered_sessions(self) -> list[TunnelSessionInfo]:
        sessions: list[TunnelSessionInfo] = []
        for cfg in self._tunnel_configs:
            sess = self._tunnel_mgr.get_session(cfg.id)
            if not sess:
                sess = TunnelSessionInfo(config=cfg)

            # Apply Type Filter
            if self._active_type_filter == "active" and sess.status != TunnelStatus.ACTIVE:
                continue
            if self._active_type_filter == "local" and cfg.tunnel_type != TunnelType.LOCAL:
                continue
            if self._active_type_filter == "remote" and cfg.tunnel_type != TunnelType.REMOTE:
                continue
            if self._active_type_filter == "socks5" and cfg.tunnel_type != TunnelType.DYNAMIC_SOCKS5:
                continue

            # Apply Search Query
            if self._search_query:
                q = self._search_query
                in_name = q in cfg.name.lower()
                in_port = q in str(cfg.local_port) or q in str(cfg.remote_port)
                in_host = q in cfg.local_host.lower() or q in cfg.remote_host.lower()
                if not (in_name or in_port or in_host):
                    continue

            sessions.append(sess)
        return sessions

    def _render_tunnels(self) -> None:
        sessions = self._get_filtered_sessions()

        # Update KPI Strip
        active_count = sum(1 for s in self._tunnel_mgr.get_all_sessions().values() if s.status == TunnelStatus.ACTIVE)
        total_count = len(self._tunnel_configs)
        self.header.set_active_count(active_count, total_count)
        if active_count > 0:
            self.kpi_active.set_data(f"{active_count} Active", f"{active_count} of {total_count} running", value_color="#34d399")
        else:
            self.kpi_active.set_data("0 Active", f"0 of {total_count} running", value_color="#94a3b8")

        # Forwarded traffic
        active_sessions = [s for s in self._tunnel_mgr.get_all_sessions().values() if s.status == TunnelStatus.ACTIVE]
        if active_sessions:
            tot_bytes = sum(s.bytes_in + s.bytes_out for s in active_sessions)
            self.kpi_traffic.set_data(f"{format_bytes(tot_bytes)}/s", f"{len(active_sessions)} active streams", value_color="#38bdf8")
        else:
            self.kpi_traffic.set_data("0 B/s", "Idle", value_color="#94a3b8")

        # Latency
        active_latencies = [s.latency_ms for s in self._tunnel_mgr.get_all_sessions().values() if s.status == TunnelStatus.ACTIVE and s.latency_ms > 0]
        if active_latencies:
            avg_lat = sum(active_latencies) / len(active_latencies)
            self.kpi_latency.set_data(f"{avg_lat:.1f} ms", "Loopback latency", value_color="#34d399")
        else:
            self.kpi_latency.set_data("--", "No active traffic", value_color="#64748b")

        # SOCKS5 status
        socks_sessions = [s for s in self._tunnel_mgr.get_all_sessions().values() if s.config.tunnel_type == TunnelType.DYNAMIC_SOCKS5 and s.status == TunnelStatus.ACTIVE]
        if socks_sessions:
            s_sess = socks_sessions[0]
            self.kpi_socks.set_data("Active", f"127.0.0.1:{s_sess.config.local_port}", value_color="#34d399")
        else:
            self.kpi_socks.set_data("Disabled", "Port 1080 Idle", value_color="#94a3b8")

        # Clear existing card widgets
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Populate cards in Split View
        for s in sessions:
            card = TunnelCardWidget(s, self)
            card.selected.connect(self._select_tunnel)
            card.toggle_requested.connect(self._on_tunnel_toggle)
            card.ping_requested.connect(self._on_tunnel_ping)
            card.delete_requested.connect(self._on_tunnel_delete)
            if s.config.id == self._selected_tunnel_id:
                card.update_selection(True)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        # Populate Dense Table View
        self.dense_table.populate(sessions)

        # Default selection
        if sessions and (not self._selected_tunnel_id or not any(s.config.id == self._selected_tunnel_id for s in sessions)):
            self._select_tunnel(sessions[0].config.id)

    def _select_tunnel(self, tunnel_id: str) -> None:
        self._selected_tunnel_id = tunnel_id
        # Highlight card
        for i in range(self.cards_layout.count() - 1):
            w = self.cards_layout.itemAt(i).widget()
            if isinstance(w, TunnelCardWidget):
                w.update_selection(w.tunnel_id == tunnel_id)

        # Update Inspector
        cfg = next((c for c in self._tunnel_configs if c.id == tunnel_id), None)
        if cfg:
            sess = self._tunnel_mgr.get_session(tunnel_id)
            if not sess:
                sess = TunnelSessionInfo(config=cfg)
            self.inspector.inspect_tunnel(sess)

    def _open_new_tunnel_dialog(self) -> None:
        dlg = NewTunnelModalDialog(self)
        if dlg.exec():
            cfg = dlg.get_config()
            self._tunnel_configs.append(cfg)
            self._select_tunnel(cfg.id)
            self._render_tunnels()
            if cfg.auto_connect and self._connection:
                self._on_tunnel_toggle(cfg.id, True)

    def _on_tunnel_toggle(self, tunnel_id: str, activate: bool) -> None:
        cfg = next((c for c in self._tunnel_configs if c.id == tunnel_id), None)
        if not cfg:
            return

        conn = self._connection
        if activate and conn is None:
            dlg = TunnelErrorDialog(
                title="No Connection",
                message="Please connect to an SSH server before starting a tunnel.",
                parent=self,
            )
            dlg.exec()
            return

        async def run_action() -> OperationResult:
            if activate:
                return await self._tunnel_mgr.start_tunnel(conn, cfg)
            else:
                return await self._tunnel_mgr.stop_tunnel(tunnel_id)

        worker = AsyncWorker(run_action)
        worker.succeeded.connect(lambda res: self._on_tunnel_action_finished(tunnel_id, res))
        worker.failed.connect(lambda err: self._on_tunnel_action_error(tunnel_id, err))
        self._track_worker(worker)

    def _on_tunnel_action_finished(self, tunnel_id: str, result: OperationResult) -> None:
        if not result.ok:
            cfg = next((c for c in self._tunnel_configs if c.id == tunnel_id), None)
            suggested_port = None
            if "port_collision" in (result.technical_details or "") or "already in use" in result.message:
                if cfg:
                    suggested_port = SSHTunnelManager.find_next_available_port(cfg.local_port + 1)

            dlg = TunnelErrorDialog(
                title="Tunnel Error",
                message=result.message,
                technical_details=result.technical_details,
                suggested_port=suggested_port,
                parent=self,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.action_use_suggested and suggested_port:
                if cfg:
                    cfg.local_port = suggested_port
                    self._render_tunnels()
                    if self._selected_tunnel_id == tunnel_id:
                        self._select_tunnel(tunnel_id)
                    # Re-trigger start with the new available port
                    self._on_tunnel_toggle(tunnel_id, True)
                    return

        self._render_tunnels()
        if self._selected_tunnel_id == tunnel_id:
            self._select_tunnel(tunnel_id)

    def _on_tunnel_action_error(self, tunnel_id: str, err: Any) -> None:
        msg = err.message if hasattr(err, "message") else str(err)
        cfg = next((c for c in self._tunnel_configs if c.id == tunnel_id), None)
        suggested_port = None
        if "already in use" in msg or "address already in use" in msg.lower():
            if cfg:
                suggested_port = SSHTunnelManager.find_next_available_port(cfg.local_port + 1)

        dlg = TunnelErrorDialog(
            title="Tunnel Error",
            message=f"Operation failed: {msg}",
            suggested_port=suggested_port,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.action_use_suggested and suggested_port:
            if cfg:
                cfg.local_port = suggested_port
                self._render_tunnels()
                if self._selected_tunnel_id == tunnel_id:
                    self._select_tunnel(tunnel_id)
                self._on_tunnel_toggle(tunnel_id, True)
                return

        self._render_tunnels()

    def _on_tunnel_ping(self, tunnel_id: str) -> None:
        cfg = next((c for c in self._tunnel_configs if c.id == tunnel_id), None)
        if not cfg:
            return

        host = "127.0.0.1" if cfg.local_host in ("localhost", "") else cfg.local_host
        port = cfg.local_port

        async def run_ping() -> tuple[bool, float, str]:
            return await asyncio.to_thread(SSHTunnelManager.test_socket_ping, host, port, 2.0)

        worker = AsyncWorker(run_ping)
        worker.succeeded.connect(lambda res: self._on_ping_finished(tunnel_id, res))
        worker.failed.connect(lambda err: self._on_ping_finished(tunnel_id, (False, 0.0, str(err))))
        self._track_worker(worker)

    def _on_ping_finished(self, tunnel_id: str, ping_res: tuple[bool, float, str]) -> None:
        reachable, lat, msg = ping_res
        sess = self._tunnel_mgr.get_session(tunnel_id)
        if not sess:
            cfg = next((c for c in self._tunnel_configs if c.id == tunnel_id), None)
            if cfg:
                sess = TunnelSessionInfo(config=cfg)
                self._tunnel_mgr._sessions[tunnel_id] = sess
        if sess:
            sess.latency_ms = lat if reachable else 0.0

        if reachable:
            self.kpi_latency.set_data(f"{lat:.1f} ms", f"Ping to port ok")
        else:
            self.kpi_latency.set_data("Offline", "Socket connection refused")

        self._render_tunnels()
        if self._selected_tunnel_id == tunnel_id:
            self._select_tunnel(tunnel_id)

    def _on_tunnel_delete(self, tunnel_id: str) -> None:
        cfg = next((c for c in self._tunnel_configs if c.id == tunnel_id), None)
        if not cfg:
            return

        confirm_dlg = ConfirmDeleteTunnelDialog(cfg.name, self)
        if confirm_dlg.exec() == QDialog.DialogCode.Accepted:
            # Stop if running asynchronously without freezing UI
            if self._tunnel_mgr.get_session(tunnel_id):
                try:
                    AsyncRuntime.instance().submit(self._tunnel_mgr.stop_tunnel(tunnel_id))
                except Exception as exc:
                    logger.warning("Failed to submit stop_tunnel: %s", exc)
            self._tunnel_configs = [c for c in self._tunnel_configs if c.id != tunnel_id]
            if self._selected_tunnel_id == tunnel_id:
                self._selected_tunnel_id = ""
            self._render_tunnels()

    def _on_traffic_tick(self) -> None:
        # Periodic sample for sparkline
        active = sum(1 for s in self._tunnel_mgr.get_all_sessions().values() if s.status == TunnelStatus.ACTIVE)
        if active > 0:
            throughput = active * 1024.0 * 2.5
            self.kpi_traffic.set_data(f"{format_bytes(throughput)}/s", f"{active} active streams", throughput, value_color="#38bdf8")
        else:
            self.kpi_traffic.set_data("0 B/s", "Idle", 0.0, value_color="#94a3b8")
