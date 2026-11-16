from __future__ import annotations

import logging
import uuid

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.tunnel_manager import (
    DEFAULT_TUNNEL_PRESETS,
    SSHTunnelManager,
    TunnelConfig,
    TunnelSessionInfo,
    TunnelStatus,
    TunnelType,
)
from ui.icons import get_icon

logger = logging.getLogger("remote_file_manager.tunnel_components")


class TunnelCardWidget(QFrame):
    """
    Card representing a single configured or active SSH Tunnel in the Master-Detail view.
    Displays directional routing topology, status pill, latency badge, toggle switch, and actions.
    Adheres strictly to Raycast / Linear dark mode design standards.
    """

    selected = Signal(str)                         # tunnel_id
    toggle_requested = Signal(str, bool)           # tunnel_id, activate
    ping_requested = Signal(str)                   # tunnel_id
    copy_requested = Signal(str)                   # text_to_copy
    delete_requested = Signal(str)                 # tunnel_id

    def __init__(self, session: TunnelSessionInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._is_selected = False

        self.setObjectName("TunnelCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._build_ui()
        self.update_selection(False)

    @property
    def tunnel_id(self) -> str:
        return self._session.config.id

    @property
    def session(self) -> TunnelSessionInfo:
        return self._session

    def update_session(self, session: TunnelSessionInfo) -> None:
        self._session = session
        self._refresh_content()

    def update_selection(self, is_selected: bool) -> None:
        self._is_selected = is_selected
        cfg = self._session.config
        is_active = self._session.status == TunnelStatus.ACTIVE

        if is_selected:
            border_color = "#6366f1"
            bg_color = "#161626"
            border_width = "1px"
        elif is_active:
            border_color = "rgba(16, 185, 129, 0.45)"
            bg_color = "#13131e"
            border_width = "1px"
        else:
            border_color = "#222232"
            bg_color = "#12121a"
            border_width = "1px"

        self.setStyleSheet(
            f"""
            QFrame#TunnelCard {{
                background-color: {bg_color};
                border: {border_width} solid {border_color};
                border-radius: 10px;
                outline: none;
            }}
            QFrame#TunnelCard:hover {{
                border-color: #4f46e5;
                background-color: #181827;
            }}
            """
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.tunnel_id)
        super().mousePressEvent(event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # 1. Top Row: Icon, Title, Type Pill, Status Pill, Toggle Switch
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.icon_box = QLabel()
        self.icon_box.setFixedSize(28, 28)
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_box.setStyleSheet(
            "background-color: rgba(99, 102, 241, 0.12); border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 6px;"
        )
        self.icon_box.setPixmap(get_icon("tunnels").pixmap(16, 16))
        top_row.addWidget(self.icon_box)

        self.name_label = QLabel(self._session.config.name)
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
        top_row.addWidget(self.name_label)

        self.type_pill = QLabel()
        self.type_pill.setStyleSheet(
            "font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; font-family: monospace;"
        )
        top_row.addWidget(self.type_pill)

        top_row.addStretch(1)

        self.status_pill = QLabel()
        self.status_pill.setStyleSheet(
            "font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px;"
        )
        top_row.addWidget(self.status_pill)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedSize(68, 26)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        top_row.addWidget(self.toggle_btn)

        layout.addLayout(top_row)

        # 2. Topology Diagram Row (Local Endpoint ──▶ Remote Target)
        topology_frame = QFrame()
        topology_frame.setObjectName("CardTopologyFrame")
        topology_frame.setStyleSheet(
            """
            QFrame#CardTopologyFrame {
                background-color: #171724;
                border: 1px solid #252536;
                border-radius: 6px;
            }
            """
        )
        topo_layout = QHBoxLayout(topology_frame)
        topo_layout.setContentsMargins(10, 6, 10, 6)
        topo_layout.setSpacing(8)

        self.local_box = QLabel()
        self.local_box.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #38bdf8; font-family: monospace; "
            "background-color: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.25); "
            "border-radius: 4px; padding: 2px 6px;"
        )
        topo_layout.addWidget(self.local_box)

        self.arrow_label = QLabel("──SSH──▶")
        self.arrow_label.setStyleSheet("font-size: 11px; font-weight: 700; color: #64748b; font-family: monospace;")
        topo_layout.addWidget(self.arrow_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.remote_box = QLabel()
        self.remote_box.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #c084fc; font-family: monospace; "
            "background-color: rgba(192, 132, 252, 0.1); border: 1px solid rgba(192, 132, 252, 0.25); "
            "border-radius: 4px; padding: 2px 6px;"
        )
        topo_layout.addWidget(self.remote_box)

        topo_layout.addStretch(1)

        self.latency_pill = QLabel()
        self.latency_pill.setStyleSheet(
            "font-size: 10px; color: #34d399; font-weight: 700; font-family: monospace; "
            "background-color: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.25); "
            "padding: 2px 6px; border-radius: 4px;"
        )
        topo_layout.addWidget(self.latency_pill)

        layout.addWidget(topology_frame)

        # 3. Bottom Row: Quick actions (Copy Endpoint, Test Ping, Delete)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        self.desc_label = QLabel(self._session.config.description or "Configured forward")
        self.desc_label.setStyleSheet("font-size: 11px; color: #888898;")
        bottom_row.addWidget(self.desc_label, 1)

        copy_btn = QPushButton("Copy Endpoint")
        copy_btn.setFixedHeight(28)
        copy_btn.setMinimumWidth(104)
        copy_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e1e2c;
                border: 1px solid #2e2e42;
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 11px;
                font-weight: 600;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #2b2b40;
                border-color: #4f46e5;
                color: #ffffff;
            }
            """
        )
        copy_btn.clicked.connect(self._on_copy_endpoint)
        bottom_row.addWidget(copy_btn)

        ping_btn = QPushButton("Ping")
        ping_btn.setFixedHeight(28)
        ping_btn.setMinimumWidth(56)
        ping_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e1e2c;
                border: 1px solid #2e2e42;
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 11px;
                font-weight: 600;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #2b2b40;
                border-color: #4f46e5;
                color: #ffffff;
            }
            """
        )
        ping_btn.clicked.connect(lambda: self.ping_requested.emit(self.tunnel_id))
        bottom_row.addWidget(ping_btn)

        del_btn = QPushButton()
        del_btn.setFixedSize(28, 28)
        del_btn.setToolTip("Delete Tunnel Configuration")
        del_btn.setIcon(get_icon("trash", color="#94a3b8", size=14))
        del_btn.setIconSize(QSize(14, 14))
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1a1a26;
                border: 1px solid #28283a;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.15);
                border: 1px solid rgba(239, 68, 68, 0.4);
            }
            """
        )
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.tunnel_id))
        bottom_row.addWidget(del_btn)

        layout.addLayout(bottom_row)

        self._refresh_content()

    def _refresh_content(self) -> None:
        cfg = self._session.config
        is_active = self._session.status == TunnelStatus.ACTIVE
        is_error = self._session.status == TunnelStatus.ERROR

        # Type Pill styling
        if cfg.tunnel_type == TunnelType.LOCAL:
            self.type_pill.setText("LOCAL -L")
            self.type_pill.setStyleSheet(
                "background-color: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: monospace;"
            )
            self.local_box.setText(f"{cfg.local_host}:{cfg.local_port}")
            self.arrow_label.setText("──SSH──▶")
            self.remote_box.setText(f"{cfg.remote_host}:{cfg.remote_port}")
        elif cfg.tunnel_type == TunnelType.REMOTE:
            self.type_pill.setText("REMOTE -R")
            self.type_pill.setStyleSheet(
                "background-color: rgba(167, 139, 250, 0.15); color: #a78bfa; border: 1px solid rgba(167, 139, 250, 0.3); padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: monospace;"
            )
            self.local_box.setText(f"{cfg.remote_host}:{cfg.remote_port}")
            self.arrow_label.setText("◀──SSH──")
            self.remote_box.setText(f"{cfg.local_host}:{cfg.local_port}")
        else:  # SOCKS5
            self.type_pill.setText("SOCKS5 -D")
            self.type_pill.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: monospace;"
            )
            self.local_box.setText(f"{cfg.local_host}:{cfg.local_port}")
            self.arrow_label.setText("──SSH──▶")
            self.remote_box.setText("🌐 Dynamic Proxy")

        # Status Pill & Toggle Action Button
        # When INACTIVE: use a clean high-contrast dark button (avoids glowing green clutter)
        if is_active:
            self.status_pill.setText("● Active")
            self.status_pill.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); color: #34d399; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px;"
            )
            self.toggle_btn.setText("Stop")
            self.toggle_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: rgba(239, 68, 68, 0.15);
                    border: 1px solid rgba(239, 68, 68, 0.35);
                    color: #f87171;
                    border-radius: 5px;
                    font-size: 11px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #ef4444;
                    color: #ffffff;
                }
                """
            )
        elif is_error:
            self.status_pill.setText("● Error")
            self.status_pill.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); color: #f87171; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px;"
            )
            self.toggle_btn.setText("Retry")
            self.toggle_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #6366f1;
                    border: none;
                    color: #ffffff;
                    border-radius: 5px;
                    font-size: 11px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #4f46e5;
                }
                """
            )
        else:
            self.status_pill.setText("○ Inactive")
            self.status_pill.setStyleSheet(
                "background-color: #1e1e2c; border: 1px solid #2b2b3c; color: #94a3b8; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px;"
            )
            self.toggle_btn.setText("Start")
            self.toggle_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #222232;
                    border: 1px solid #36364c;
                    color: #e2e8f0;
                    border-radius: 5px;
                    font-size: 11px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #6366f1;
                    border-color: #6366f1;
                    color: #ffffff;
                }
                """
            )

        # Latency
        if self._session.latency_ms > 0:
            self.latency_pill.setText(f"{self._session.latency_ms:.1f}ms")
            self.latency_pill.setVisible(True)
        else:
            self.latency_pill.setVisible(False)

        self.update_selection(self._is_selected)

    def _on_toggle_clicked(self) -> None:
        target_state = self._session.status != TunnelStatus.ACTIVE
        self.toggle_requested.emit(self.tunnel_id, target_state)

    def _on_copy_endpoint(self) -> None:
        cfg = self._session.config
        ep = f"{cfg.local_host}:{cfg.local_port}"
        QApplication.clipboard().setText(ep)
        self.copy_requested.emit(ep)


class TunnelInspectorWidget(QFrame):
    """
    Inspector Panel for selected SSH Tunnel.
    Displays OpenSSH CLI string, socket health matrix, client streams, and log stream.
    """

    toggle_requested = Signal(str, bool)
    ping_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TunnelInspector")
        self.setStyleSheet(
            """
            QFrame#TunnelInspector {
                background-color: #14141e;
                border: 1px solid #242436;
                border-radius: 12px;
            }
            """
        )
        self._session: TunnelSessionInfo | None = None
        self._host_info = ("example.com", "ubuntu", 22)
        self._build_ui()

    def set_host_context(self, host: str, username: str, port: int = 22) -> None:
        self._host_info = (host, username, port)
        if self._session:
            self.inspect_tunnel(self._session)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        # Header: Title + Type Badge + Toggle button
        header = QHBoxLayout()
        header.setSpacing(8)

        self.title_label = QLabel("Tunnel Inspector")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        header.addWidget(self.title_label)

        self.type_badge = QLabel("LOCAL -L")
        self.type_badge.setStyleSheet(
            "background-color: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: monospace;"
        )
        header.addWidget(self.type_badge)

        header.addStretch(1)

        self.toggle_btn = QPushButton("Start Tunnel")
        self.toggle_btn.setFixedSize(104, 28)
        self.toggle_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            """
        )
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        header.addWidget(self.toggle_btn)

        layout.addLayout(header)

        # OpenSSH CLI Command Box
        cli_box_container = QFrame()
        cli_box_container.setObjectName("CliBoxContainer")
        cli_box_container.setStyleSheet(
            """
            QFrame#CliBoxContainer {
                background-color: #171724;
                border: 1px solid #252536;
                border-radius: 8px;
            }
            """
        )
        cli_l = QVBoxLayout(cli_box_container)
        cli_l.setContentsMargins(12, 10, 12, 10)
        cli_l.setSpacing(8)

        cli_header = QHBoxLayout()
        cli_lbl = QLabel("OPENSSH COMMAND EQUIVALENT")
        cli_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        cli_header.addWidget(cli_lbl)
        cli_header.addStretch(1)

        copy_cli_btn = QPushButton("Copy CLI")
        copy_cli_btn.setFixedSize(78, 24)
        copy_cli_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #222232;
                border: 1px solid #343448;
                border-radius: 5px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2e2e44;
                border-color: #4f46e5;
                color: #ffffff;
            }
            """
        )
        copy_cli_btn.clicked.connect(self._copy_cli_command)
        cli_header.addWidget(copy_cli_btn)
        cli_l.addLayout(cli_header)

        self.cli_command_label = QLabel("ssh -N -L 5433:127.0.0.1:5432 ubuntu@server")
        self.cli_command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cli_command_label.setStyleSheet(
            "font-family: monospace; font-size: 11px; font-weight: 600; color: #38bdf8; background: transparent; padding: 2px 0;"
        )
        cli_l.addWidget(self.cli_command_label)

        layout.addWidget(cli_box_container)

        # 2x2 Diagnostics Grid
        diag_container = QFrame()
        diag_container.setObjectName("DiagContainer")
        diag_container.setStyleSheet(
            """
            QFrame#DiagContainer {
                background-color: #171724;
                border: 1px solid #252536;
                border-radius: 8px;
            }
            """
        )
        diag_l = QVBoxLayout(diag_container)
        diag_l.setContentsMargins(12, 10, 12, 10)
        diag_l.setSpacing(10)

        diag_hdr = QHBoxLayout()
        d_title = QLabel("SOCKET DIAGNOSTICS & TELEMETRY")
        d_title.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        diag_hdr.addWidget(d_title)
        diag_hdr.addStretch(1)

        self.ping_btn = QPushButton("Test Latency")
        self.ping_btn.setFixedSize(94, 24)
        self.ping_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #222232;
                border: 1px solid #343448;
                border-radius: 5px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2e2e44;
                border-color: #4f46e5;
                color: #ffffff;
            }
            """
        )
        self.ping_btn.clicked.connect(self._on_ping_clicked)
        diag_hdr.addWidget(self.ping_btn)
        diag_l.addLayout(diag_hdr)

        grid_l = QHBoxLayout()
        grid_l.setSpacing(10)

        # Col 1: Local Endpoint & Remote Endpoint
        col1 = QVBoxLayout()
        col1.setSpacing(4)
        col1.addWidget(self._make_label("Local Bind Endpoint:", "font-size: 10px; color: #94a3b8;"))
        self.val_local = QLabel("127.0.0.1:5433 (Listening)")
        self.val_local.setStyleSheet("font-size: 11px; font-family: monospace; font-weight: 700; color: #ffffff;")
        col1.addWidget(self.val_local)

        col1.addSpacing(2)
        col1.addWidget(self._make_label("Remote Target Endpoint:", "font-size: 10px; color: #94a3b8;"))
        self.val_remote = QLabel("127.0.0.1:5432")
        self.val_remote.setStyleSheet("font-size: 11px; font-family: monospace; font-weight: 700; color: #ffffff;")
        col1.addWidget(self.val_remote)
        grid_l.addLayout(col1)

        # Col 2: Roundtrip Latency & Active Streams
        col2 = QVBoxLayout()
        col2.setSpacing(4)
        col2.addWidget(self._make_label("Socket Latency:", "font-size: 10px; color: #94a3b8;"))
        self.val_latency = QLabel("--")
        self.val_latency.setStyleSheet("font-size: 11px; font-family: monospace; font-weight: 700; color: #94a3b8;")
        col2.addWidget(self.val_latency)

        col2.addSpacing(2)
        col2.addWidget(self._make_label("Active Client Streams:", "font-size: 10px; color: #94a3b8;"))
        self.val_streams = QLabel("0 connected clients")
        self.val_streams.setStyleSheet("font-size: 11px; font-family: monospace; font-weight: 700; color: #ffffff;")
        col2.addWidget(self.val_streams)
        grid_l.addLayout(col2)

        diag_l.addLayout(grid_l)
        layout.addWidget(diag_container)

        # Active Client Streams Table
        streams_lbl = QLabel("ACTIVE FORWARDED STREAMS")
        streams_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        layout.addWidget(streams_lbl)

        self.streams_table = QTableWidget(0, 4)
        self.streams_table.setHorizontalHeaderLabels(["CLIENT", "DESTINATION", "DURATION", "STATUS"])
        self.streams_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.streams_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.streams_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.streams_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.streams_table.verticalHeader().setVisible(False)
        self.streams_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.streams_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.streams_table.setFixedHeight(105)
        self.streams_table.setStyleSheet(
            """
            QTableWidget {
                background-color: #12121a;
                border: 1px solid #222232;
                border-radius: 8px;
                gridline-color: #1a1a24;
                font-size: 11px;
                font-family: monospace;
            }
            QHeaderView::section {
                background-color: #181824;
                color: #94a3b8;
                font-size: 10px;
                font-weight: 700;
                border: none;
                padding: 5px 8px;
            }
            """
        )
        layout.addWidget(self.streams_table)

        # Live Event Log Console
        log_hdr = QHBoxLayout()
        log_title = QLabel("FORWARDING EVENT LOG")
        log_title.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        log_hdr.addWidget(log_title)
        log_hdr.addStretch(1)

        self.log_count = QLabel("0 events")
        self.log_count.setStyleSheet("font-size: 10px; color: #71717a;")
        log_hdr.addWidget(self.log_count)
        layout.addLayout(log_hdr)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet(
            """
            QTextEdit {
                background-color: #0d0d14;
                border: 1px solid #222232;
                border-radius: 8px;
                color: #cbd5e1;
                font-family: monospace;
                font-size: 11px;
                padding: 8px;
            }
            """
        )
        layout.addWidget(self.log_edit, 1)

    def _make_label(self, text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def inspect_tunnel(self, session: TunnelSessionInfo) -> None:
        self._session = session
        cfg = session.config
        host, user, port = self._host_info

        self.title_label.setText(cfg.name)

        if cfg.tunnel_type == TunnelType.LOCAL:
            self.type_badge.setText("LOCAL -L")
            self.type_badge.setStyleSheet(
                "background-color: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: monospace;"
            )
            self.val_local.setText(f"{cfg.local_host}:{cfg.local_port}")
            self.val_remote.setText(f"{cfg.remote_host}:{cfg.remote_port}")
        elif cfg.tunnel_type == TunnelType.REMOTE:
            self.type_badge.setText("REMOTE -R")
            self.type_badge.setStyleSheet(
                "background-color: rgba(167, 139, 250, 0.15); color: #a78bfa; border: 1px solid rgba(167, 139, 250, 0.3); padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: monospace;"
            )
            self.val_local.setText(f"{cfg.remote_host}:{cfg.remote_port} (Remote Listen)")
            self.val_remote.setText(f"{cfg.local_host}:{cfg.local_port} (Local Target)")
        else:
            self.type_badge.setText("SOCKS5 -D")
            self.type_badge.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: monospace;"
            )
            self.val_local.setText(f"{cfg.local_host}:{cfg.local_port} (SOCKS5 Proxy)")
            self.val_remote.setText("Dynamic Internet via SSH")

        # OpenSSH command string
        cli_cmd = SSHTunnelManager.generate_openssh_command(cfg, host=host, username=user, port=port)
        self.cli_command_label.setText(cli_cmd)

        is_active = session.status == TunnelStatus.ACTIVE
        if is_active:
            self.toggle_btn.setText("Stop Tunnel")
            self.toggle_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: rgba(239, 68, 68, 0.15);
                    border: 1px solid rgba(239, 68, 68, 0.35);
                    color: #f87171;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #ef4444;
                    color: #ffffff;
                }
                """
            )
        else:
            self.toggle_btn.setText("Start Tunnel")
            self.toggle_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #6366f1;
                    border: none;
                    color: #ffffff;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #4f46e5;
                }
                """
            )

        if session.latency_ms > 0:
            self.val_latency.setText(f"{session.latency_ms:.1f}ms")
            self.val_latency.setStyleSheet("font-size: 11px; font-family: monospace; font-weight: 700; color: #34d399;")
        else:
            self.val_latency.setText("--")
            self.val_latency.setStyleSheet("font-size: 11px; font-family: monospace; font-weight: 700; color: #94a3b8;")

        self.val_streams.setText(f"{session.active_connections} connected clients")

        # Populate active streams table correctly
        self.streams_table.setRowCount(0)
        if session.streams:
            for r, stream in enumerate(session.streams):
                self.streams_table.insertRow(r)
                self.streams_table.setItem(r, 0, QTableWidgetItem(stream.client_addr))
                self.streams_table.setItem(r, 1, QTableWidgetItem(stream.target_addr))
                self.streams_table.setItem(r, 2, QTableWidgetItem(f"{stream.duration_sec:.1f}s"))
                self.streams_table.setItem(r, 3, QTableWidgetItem(stream.status))
        else:
            self.streams_table.insertRow(0)
            item_idle = QTableWidgetItem("No active client streams currently connected")
            item_idle.setForeground(QColor("#64748b"))
            self.streams_table.setItem(0, 0, item_idle)
            for c in range(1, 4):
                item_dash = QTableWidgetItem("--")
                item_dash.setForeground(QColor("#64748b"))
                self.streams_table.setItem(0, c, item_dash)

        # Update logs
        if is_active:
            log_text = (
                f"[{session.config.name}] Tunnel active and listening on {cfg.local_host}:{cfg.local_port}\n"
                f"[{session.config.name}] Forwarding channels configured over active SSH connection\n"
            )
        elif session.status == TunnelStatus.ERROR:
            log_text = f"[{session.config.name}] ERROR: {session.error_msg}\n"
        else:
            log_text = f"[{session.config.name}] Tunnel is currently stopped/inactive.\n"

        self.log_edit.setText(log_text)
        num_events = len([line for line in log_text.strip().split("\n") if line])
        self.log_count.setText(f"{num_events} event{'s' if num_events != 1 else ''}")

    def _copy_cli_command(self) -> None:
        cmd = self.cli_command_label.text().strip()
        QApplication.clipboard().setText(cmd)

    def _on_toggle_clicked(self) -> None:
        if self._session:
            target = self._session.status != TunnelStatus.ACTIVE
            self.toggle_requested.emit(self._session.config.id, target)

    def _on_ping_clicked(self) -> None:
        if self._session:
            self.ping_requested.emit(self._session.config.id)


class TunnelDenseTableView(QTableWidget):
    """
    High-density table view for managing 50+ port forwarding tunnels simultaneously.
    """

    unit_selected = Signal(str)
    toggle_requested = Signal(str, bool)
    delete_requested = Signal(str)
    ping_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 8, parent)
        self.setHorizontalHeaderLabels([
            "STATUS", "NAME", "TYPE", "LOCAL ENDPOINT", "REMOTE TARGET", "LATENCY", "ACTIONS", "TOGGLE"
        ])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setStyleSheet(
            """
            QTableWidget {
                background-color: #0e0e14;
                border: 1px solid #232330;
                border-radius: 8px;
                gridline-color: #1a1a24;
                color: #e2e8f0;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #15151e;
                color: #94a3b8;
                font-size: 10px;
                font-weight: 700;
                border: none;
                padding: 6px 8px;
            }
            QTableWidget::item:selected {
                background-color: #1f1f2e;
                color: #ffffff;
            }
            """
        )
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def populate(self, sessions: list[TunnelSessionInfo]) -> None:
        self.setRowCount(0)
        for row, s in enumerate(sessions):
            self.insertRow(row)
            cfg = s.config
            is_active = s.status == TunnelStatus.ACTIVE

            # 0. Status
            status_text = "● Active" if is_active else ("● Error" if s.status == TunnelStatus.ERROR else "○ Inactive")
            item_stat = QTableWidgetItem(status_text)
            stat_color = "#34d399" if is_active else ("#f87171" if s.status == TunnelStatus.ERROR else "#94a3b8")
            item_stat.setForeground(QColor(stat_color))
            item_stat.setData(Qt.ItemDataRole.UserRole, cfg.id)
            self.setItem(row, 0, item_stat)

            # 1. Name
            item_name = QTableWidgetItem(cfg.name)
            item_name.setForeground(QColor("#ffffff"))
            item_name.setFont(QFont("system-ui", 10, QFont.Weight.Bold))
            self.setItem(row, 1, item_name)

            # 2. Type
            type_str = "Local (-L)" if cfg.tunnel_type == TunnelType.LOCAL else ("Remote (-R)" if cfg.tunnel_type == TunnelType.REMOTE else "SOCKS5 (-D)")
            item_type = QTableWidgetItem(type_str)
            item_type.setForeground(QColor("#38bdf8" if cfg.tunnel_type == TunnelType.LOCAL else ("#a78bfa" if cfg.tunnel_type == TunnelType.REMOTE else "#34d399")))
            self.setItem(row, 2, item_type)

            # 3. Local Endpoint
            item_local = QTableWidgetItem(f"{cfg.local_host}:{cfg.local_port}")
            item_local.setForeground(QColor("#cbd5e1"))
            self.setItem(row, 3, item_local)

            # 4. Remote Target
            remote_str = f"{cfg.remote_host}:{cfg.remote_port}" if cfg.tunnel_type != TunnelType.DYNAMIC_SOCKS5 else "Dynamic Proxy"
            item_remote = QTableWidgetItem(remote_str)
            item_remote.setForeground(QColor("#cbd5e1"))
            self.setItem(row, 4, item_remote)

            # 5. Latency
            lat_str = f"{s.latency_ms:.1f}ms" if s.latency_ms > 0 else "-"
            item_lat = QTableWidgetItem(lat_str)
            item_lat.setForeground(QColor("#34d399" if s.latency_ms > 0 else "#64748b"))
            self.setItem(row, 5, item_lat)

            # 6. Action: Ping & Delete
            act_widget = QWidget()
            act_l = QHBoxLayout(act_widget)
            act_l.setContentsMargins(4, 2, 4, 2)
            act_l.setSpacing(4)

            p_btn = QPushButton("Ping")
            p_btn.setFixedSize(44, 22)
            p_btn.setStyleSheet("background-color: #1e1e2a; color: #cbd5e1; border: 1px solid #2d2d3e; border-radius: 4px; font-size: 10px; font-weight: 600;")
            p_btn.clicked.connect((lambda tid=cfg.id: lambda: self.ping_requested.emit(tid))())
            act_l.addWidget(p_btn)

            d_btn = QPushButton()
            d_btn.setFixedSize(22, 22)
            d_btn.setIcon(get_icon("trash"))
            d_btn.setIconSize(QSize(12, 12))
            d_btn.setToolTip("Delete Tunnel Configuration")
            d_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(239, 68, 68, 0.15);
                    border: 1px solid rgba(239, 68, 68, 0.35);
                }
                """
            )
            d_btn.clicked.connect((lambda tid=cfg.id: lambda: self.delete_requested.emit(tid))())
            act_l.addWidget(d_btn)
            self.setCellWidget(row, 6, act_widget)

            # 7. Toggle Button
            tog_btn = QPushButton("Stop" if is_active else "Start")
            tog_btn.setFixedSize(54, 22)
            if is_active:
                tog_btn.setStyleSheet("background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 4px; font-size: 10px; font-weight: 700;")
            else:
                tog_btn.setStyleSheet("background-color: #222232; color: #e2e8f0; border: 1px solid #36364c; border-radius: 4px; font-size: 10px; font-weight: 700;")
            tog_btn.clicked.connect((lambda tid=cfg.id, act=not is_active: lambda: self.toggle_requested.emit(tid, act))())
            self.setCellWidget(row, 7, tog_btn)

    def _on_selection_changed(self) -> None:
        sel = self.selectedItems()
        if sel:
            tid = self.item(sel[0].row(), 0).data(Qt.ItemDataRole.UserRole)
            if tid:
                self.unit_selected.emit(tid)


class NewTunnelModalDialog(QDialog):
    """
    Dialog for configuring a new SSH Port Forwarding Tunnel or SOCKS5 Proxy.
    Includes presets for Postgres, MySQL, Redis, MongoDB, Web Dev, and SOCKS5.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NewTunnelModalDialog")
        self.setWindowTitle("New SSH Port Forwarding Tunnel")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedSize(620, 560)
        self.setStyleSheet(
            """
            QDialog#NewTunnelModalDialog {
                background-color: #13131c;
            }
            """
        )
        self._preset_buttons: list[QPushButton] = []
        self._build_ui()
        self._apply_preset(DEFAULT_TUNNEL_PRESETS[0])

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # 1. Header
        header = QVBoxLayout()
        header.setSpacing(3)
        title = QLabel("Create Port Forwarding Tunnel")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        header.addWidget(title)

        sub = QLabel("Forward local ports through the encrypted SSH tunnel to remote services.")
        sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        header.addWidget(sub)
        layout.addLayout(header)

        # 2. Presets Row
        presets_bar = QVBoxLayout()
        presets_bar.setSpacing(6)
        p_lbl = QLabel("POPULAR PRESETS:")
        p_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        presets_bar.addWidget(p_lbl)

        p_buttons = QHBoxLayout()
        p_buttons.setSpacing(6)
        for i, preset in enumerate(DEFAULT_TUNNEL_PRESETS):
            b = QPushButton(preset["name"].split()[0])
            b.setCheckable(True)
            if i == 0:
                b.setChecked(True)
            b.setToolTip(preset["description"])
            b.setStyleSheet(
                """
                QPushButton {
                    background-color: #171724;
                    border: 1px solid #252538;
                    border-radius: 6px;
                    color: #cbd5e1;
                    padding: 4px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #222234;
                    color: #ffffff;
                    border-color: #4f46e5;
                }
                QPushButton:checked {
                    background-color: rgba(99, 102, 241, 0.2);
                    border-color: #6366f1;
                    color: #ffffff;
                }
                """
            )
            b.clicked.connect((lambda p=preset, btn=b: lambda: self._on_preset_btn_clicked(btn, p))())
            p_buttons.addWidget(b)
            self._preset_buttons.append(b)
        p_buttons.addStretch(1)
        presets_bar.addLayout(p_buttons)
        layout.addLayout(presets_bar)

        # 3. Tunnel Mode Selection Cards (-L, -R, -D)
        mode_box = QHBoxLayout()
        mode_box.setSpacing(14)

        self.btn_group_mode = QButtonGroup(self)

        radio_style = """
            QRadioButton {
                color: #cbd5e1;
                font-weight: 600;
                font-size: 11px;
                spacing: 6px;
            }
            QRadioButton:checked {
                color: #ffffff;
                font-weight: 700;
            }
            QRadioButton::indicator {
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 1px solid #36364a;
                background-color: #181824;
            }
            QRadioButton::indicator:checked {
                border-color: #6366f1;
                background-color: #6366f1;
            }
        """

        self.card_local = QRadioButton("Local Forward (-L)")
        self.card_local.setChecked(True)
        self.card_local.setStyleSheet(radio_style)
        self.card_local.toggled.connect(self._on_mode_changed)
        self.btn_group_mode.addButton(self.card_local, 0)
        mode_box.addWidget(self.card_local)

        self.card_remote = QRadioButton("Remote Forward (-R)")
        self.card_remote.setStyleSheet(radio_style)
        self.card_remote.toggled.connect(self._on_mode_changed)
        self.btn_group_mode.addButton(self.card_remote, 1)
        mode_box.addWidget(self.card_remote)

        self.card_socks = QRadioButton("Dynamic SOCKS5 (-D)")
        self.card_socks.setStyleSheet(radio_style)
        self.card_socks.toggled.connect(self._on_mode_changed)
        self.btn_group_mode.addButton(self.card_socks, 2)
        mode_box.addWidget(self.card_socks)

        mode_box.addStretch(1)
        layout.addLayout(mode_box)

        # 4. Inputs Form
        fields_l = QVBoxLayout()
        fields_l.setSpacing(8)

        # Tunnel Name
        fields_l.addWidget(self._make_field_label("Tunnel Name"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., PostgreSQL Production Access")
        self.name_input.setStyleSheet(self._input_style())
        self.name_input.textChanged.connect(self._sync_cli_preview)
        fields_l.addWidget(self.name_input)

        # Local & Remote Endpoints Row
        ports_row = QHBoxLayout()
        ports_row.setSpacing(10)

        # Local side
        loc_col = QVBoxLayout()
        loc_col.setSpacing(4)
        loc_col.addWidget(self._make_field_label("Local Bind Endpoint"))
        loc_h = QHBoxLayout()
        loc_h.setSpacing(6)
        self.local_host_input = QLineEdit("127.0.0.1")
        self.local_host_input.setStyleSheet(self._input_style())
        self.local_host_input.textChanged.connect(self._sync_cli_preview)
        loc_h.addWidget(self.local_host_input, 3)

        self.local_port_input = QLineEdit("5433")
        self.local_port_input.setStyleSheet(self._input_style())
        self.local_port_input.textChanged.connect(self._sync_cli_preview)
        loc_h.addWidget(self.local_port_input, 2)
        loc_col.addLayout(loc_h)
        ports_row.addLayout(loc_col)

        # Remote side
        rem_col = QVBoxLayout()
        rem_col.setSpacing(4)
        self.rem_label = self._make_field_label("Remote Target Endpoint")
        rem_col.addWidget(self.rem_label)
        rem_h = QHBoxLayout()
        rem_h.setSpacing(6)
        self.remote_host_input = QLineEdit("127.0.0.1")
        self.remote_host_input.setStyleSheet(self._input_style())
        self.remote_host_input.textChanged.connect(self._sync_cli_preview)
        rem_h.addWidget(self.remote_host_input, 3)

        self.remote_port_input = QLineEdit("5432")
        self.remote_port_input.setStyleSheet(self._input_style())
        self.remote_port_input.textChanged.connect(self._sync_cli_preview)
        rem_h.addWidget(self.remote_port_input, 2)
        rem_col.addLayout(rem_h)
        ports_row.addLayout(rem_col)

        fields_l.addLayout(ports_row)

        # Description
        fields_l.addWidget(self._make_field_label("Description (Optional)"))
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Notes or team access usage...")
        self.desc_input.setStyleSheet(self._input_style())
        fields_l.addWidget(self.desc_input)

        # Auto-connect checkbox
        self.auto_connect_check = QCheckBox("Auto-connect when SSH session establishes")
        self.auto_connect_check.setStyleSheet(
            """
            QCheckBox {
                color: #cbd5e1;
                font-size: 11px;
                font-weight: 500;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border-radius: 4px;
                border: 1px solid #3b3b4f;
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
        )
        fields_l.addWidget(self.auto_connect_check)

        layout.addLayout(fields_l)

        # 5. OpenSSH Command Preview
        preview_box = QFrame()
        preview_box.setObjectName("PreviewBox")
        preview_box.setStyleSheet(
            """
            QFrame#PreviewBox {
                background-color: #0e0e16;
                border: 1px solid #222232;
                border-radius: 6px;
            }
            """
        )
        prev_l = QVBoxLayout(preview_box)
        prev_l.setContentsMargins(10, 8, 10, 8)
        prev_l.setSpacing(4)

        prev_lbl = QLabel("COMMAND EQUIVALENT PREVIEW")
        prev_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; border: none; background: transparent;")
        prev_l.addWidget(prev_lbl)

        self.preview_cmd_label = QLabel("ssh -N -L 5433:127.0.0.1:5432 user@host")
        self.preview_cmd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_cmd_label.setStyleSheet("font-family: monospace; font-size: 11px; color: #38bdf8; border: none; background: transparent;")
        prev_l.addWidget(self.preview_cmd_label)
        layout.addWidget(preview_box)

        # 6. Action Buttons
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "background-color: #1e1e2c; border: 1px solid #2e2e42; border-radius: 6px; color: #cbd5e1; padding: 6px 16px; font-weight: 600; font-size: 11px;"
        )
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)

        save_btn = QPushButton("Create Tunnel")
        save_btn.setStyleSheet(
            "background-color: #6366f1; border: none; border-radius: 6px; color: #ffffff; padding: 6px 20px; font-weight: 700; font-size: 11px;"
        )
        save_btn.clicked.connect(self._on_save_clicked)
        actions.addWidget(save_btn)

        layout.addLayout(actions)

    def _on_preset_btn_clicked(self, clicked_btn: QPushButton, preset: dict) -> None:
        for b in self._preset_buttons:
            b.setChecked(b is clicked_btn)
        self._apply_preset(preset)

    def _make_field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #94a3b8;")
        return lbl

    def _input_style(self) -> str:
        return """
            QLineEdit {
                background-color: #101018;
                border: 1px solid #28283c;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #6366f1;
            }
        """

    def _apply_preset(self, preset: dict) -> None:
        self.name_input.setText(preset["name"])
        tt = preset["tunnel_type"]
        if tt == TunnelType.LOCAL:
            self.card_local.setChecked(True)
        elif tt == TunnelType.REMOTE:
            self.card_remote.setChecked(True)
        else:
            self.card_socks.setChecked(True)

        self.local_host_input.setText(preset["local_host"])
        self.local_port_input.setText(str(preset["local_port"]))
        self.remote_host_input.setText(preset["remote_host"])
        self.remote_port_input.setText(str(preset["remote_port"]))
        self.desc_input.setText(preset["description"])
        self._sync_cli_preview()

    def _on_mode_changed(self) -> None:
        is_socks = self.card_socks.isChecked()
        self.remote_host_input.setEnabled(not is_socks)
        self.remote_port_input.setEnabled(not is_socks)
        self.rem_label.setText("Remote Target (Disabled for SOCKS5)" if is_socks else "Remote Target Endpoint")
        self._sync_cli_preview()

    def _sync_cli_preview(self) -> None:
        cfg = self.get_config()
        cmd = SSHTunnelManager.generate_openssh_command(cfg, host="host", username="user")
        self.preview_cmd_label.setText(cmd)

    def _on_save_clicked(self) -> None:
        # Validate ports
        try:
            lp = int(self.local_port_input.text().strip())
            if lp <= 0 or lp > 65535:
                raise ValueError()
        except ValueError:
            QMessageBox.warning(self, "Invalid Port", "Local port must be an integer between 1 and 65535.")
            return

        if not self.card_socks.isChecked():
            try:
                rp = int(self.remote_port_input.text().strip())
                if rp <= 0 or rp > 65535:
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, "Invalid Port", "Remote port must be an integer between 1 and 65535.")
                return

        self.accept()

    def get_config(self) -> TunnelConfig:
        if self.card_local.isChecked():
            tt = TunnelType.LOCAL
        elif self.card_remote.isChecked():
            tt = TunnelType.REMOTE
        else:
            tt = TunnelType.DYNAMIC_SOCKS5

        try:
            lp = int(self.local_port_input.text().strip())
        except ValueError:
            lp = 8080

        try:
            rp = int(self.remote_port_input.text().strip())
        except ValueError:
            rp = 80

        return TunnelConfig(
            id=uuid.uuid4().hex[:8],
            name=self.name_input.text().strip() or "Custom Tunnel",
            tunnel_type=tt,
            local_host=self.local_host_input.text().strip() or "127.0.0.1",
            local_port=lp,
            remote_host=self.remote_host_input.text().strip() or "127.0.0.1",
            remote_port=rp,
            auto_connect=self.auto_connect_check.isChecked(),
            description=self.desc_input.text().strip(),
        )
