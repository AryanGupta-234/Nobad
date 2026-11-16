from __future__ import annotations

import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.icons import get_icon
from ui.theme import DEFAULT_THEME
from ui.workbench import StatusBadge
from ui.workbench_models import build_connection_request


class PingWorker(QThread):
    ping_result = Signal(bool, float, str)

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self.host = host
        self.port = port

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((self.host, self.port))
            sock.close()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.ping_result.emit(True, elapsed_ms, f"Reachable in {elapsed_ms:.1f}ms")
        except Exception as exc:
            self.ping_result.emit(False, 0.0, f"Cannot connect: {exc}")


class NewHostPanel(QWidget):
    connect_requested = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._ping_worker: PingWorker | None = None

        # 1. Header Box
        header_box = QHBoxLayout()
        header_box.setContentsMargins(0, 0, 0, 0)
        header_box.setSpacing(10)

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        page_title = QLabel("Add New Connection")
        page_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f4f4f5; letter-spacing: -0.02em;")
        self.status_detail = QLabel("Configure an SSH/SFTP, FTP/FTPS, or rclone cloud endpoint")
        self.status_detail.setStyleSheet("font-size: 12px; color: #71717a;")
        title_layout.addWidget(page_title)
        title_layout.addWidget(self.status_detail)

        self.status_badge = StatusBadge("Ready")
        header_box.addLayout(title_layout, 1)
        header_box.addWidget(self.status_badge)

        # 2. Quick Connection URL Parser Bar
        quick_bar = QFrame()
        quick_bar.setObjectName("QuickBar")
        quick_bar.setStyleSheet(f"""
            QFrame#QuickBar {{
                background-color: {DEFAULT_THEME.surface};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 8px;
                padding: 4px 8px;
            }}
        """)
        quick_layout = QHBoxLayout(quick_bar)
        quick_layout.setContentsMargins(4, 4, 4, 4)
        quick_layout.setSpacing(8)

        quick_label = QLabel("QUICK PASTE:")
        quick_label.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 700; color: #818cf8; background: transparent; border: none;")

        self.quick_input = QLineEdit()
        self.quick_input.setPlaceholderText("ssh -p 22 ubuntu@168.231.121.7 or sftp://user:pass@host:22")
        self.quick_input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: 0;
                font-family: 'JetBrains Mono', monospace;
                font-size: 12px;
                color: #f4f4f5;
            }
        """)

        self.parse_btn = QPushButton("Auto-Fill Form")
        self.parse_btn.setFixedHeight(26)
        self.parse_btn.setStyleSheet("""
            QPushButton {
                background: #141418;
                border: 1px solid #1e1e24;
                border-radius: 5px;
                color: #a1a1aa;
                font-size: 11px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: #1e1e24;
                color: #f4f4f5;
            }
        """)

        quick_layout.addWidget(quick_label)
        quick_layout.addWidget(self.quick_input, 1)
        quick_layout.addWidget(self.parse_btn)

        # 3. Two-Column Card Form
        form_row = QHBoxLayout()
        form_row.setContentsMargins(0, 0, 0, 0)
        form_row.setSpacing(14)

        # Column 1: Protocol & Credentials
        col1 = QFrame()
        col1.setObjectName("NewHostCol1")
        col1.setStyleSheet(f"""
            QFrame#NewHostCol1 {{
                background-color: {DEFAULT_THEME.surface};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 10px;
            }}
        """)
        col1_layout = QVBoxLayout(col1)
        col1_layout.setContentsMargins(14, 14, 14, 14)
        col1_layout.setSpacing(10)

        c1_title = QLabel("PROTOCOL & CREDENTIALS")
        c1_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.05em;")
        col1_layout.addWidget(c1_title)

        # Protocol Segmented Selector
        self.protocol_group = QButtonGroup(self)
        self.protocol_group.setExclusive(True)

        proto_box = QHBoxLayout()
        proto_box.setContentsMargins(0, 0, 0, 0)
        proto_box.setSpacing(6)

        self.btn_sftp = QPushButton("SFTP / SSH")
        self.btn_ftps = QPushButton("FTPS (Explicit)")
        self.btn_ftp = QPushButton("FTP")
        self.btn_rclone = QPushButton("rclone")

        for btn, name in ((self.btn_sftp, "SSH"), (self.btn_ftps, "FTPS"), (self.btn_ftp, "FTP"), (self.btn_rclone, "rclone")):
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setStyleSheet("""
                QPushButton {
                    background: #141418;
                    border: 1px solid #1e1e24;
                    border-radius: 6px;
                    color: #a1a1aa;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: #1e1e24;
                    color: #f4f4f5;
                }
                QPushButton:checked {
                    background: rgba(99, 102, 241, 0.2);
                    border: 1px solid #6366f1;
                    color: #a5b4fc;
                    font-weight: 600;
                }
            """)
            self.protocol_group.addButton(btn)
            proto_box.addWidget(btn)

        self.btn_sftp.setChecked(True)
        col1_layout.addLayout(proto_box)

        # Internal QComboBox kept for full API compatibility with MainWindow
        self.protocol = QComboBox()
        self.protocol.addItems(["SSH", "SFTP", "FTP", "FTPS", "rclone"])
        self.protocol.setVisible(False)

        # Fields
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("e.g. Production Cluster")
        col1_layout.addWidget(self._make_field("Profile Name", self.profile_name))

        host_port_box = QHBoxLayout()
        self.host = QLineEdit()
        self.host.setPlaceholderText("168.231.121.7 or server.internal")
        self.host.setStyleSheet("font-family: 'JetBrains Mono', monospace;")
        self.port = QLineEdit("22")
        self.port.setFixedWidth(70)
        self.port.setStyleSheet("font-family: 'JetBrains Mono', monospace; text-align: center;")

        host_port_box.addWidget(self._make_field("Hostname / IP", self.host), 1)
        host_port_box.addWidget(self._make_field("Port", self.port))
        col1_layout.addLayout(host_port_box)

        self.username = QLineEdit()
        self.username.setPlaceholderText("root, ubuntu, etc.")
        self.username.setStyleSheet("font-family: 'JetBrains Mono', monospace;")
        col1_layout.addWidget(self._make_field("Username", self.username))

        # Auth Selector
        self.auth_type = QComboBox()
        self.auth_type.addItems(["Password", "SSH Key", "SSH Agent"])
        col1_layout.addWidget(self._make_field("Authentication Method", self.auth_type))

        # Secret (Password / Passphrase)
        self.secret = QLineEdit()
        self.secret.setPlaceholderText("Password or private key passphrase")
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        col1_layout.addWidget(self._make_field("Secret / Passphrase", self.secret))

        # SSH Key Path
        key_box = QHBoxLayout()
        self.key_path = QLineEdit()
        self.key_path.setPlaceholderText("~/.ssh/id_ed25519 or .pem")
        self.key_path.setStyleSheet("font-family: 'JetBrains Mono', monospace;")
        self.browse_key = QPushButton("Browse")
        self.browse_key.setFixedHeight(28)
        key_box.addWidget(self.key_path, 1)
        key_box.addWidget(self.browse_key)
        col1_layout.addWidget(self._make_field("SSH Private Key", key_box))

        col1_layout.addStretch()

        # Column 2: Workspaces, Security & Advanced
        col2 = QFrame()
        col2.setObjectName("NewHostCol2")
        col2.setStyleSheet(f"""
            QFrame#NewHostCol2 {{
                background-color: {DEFAULT_THEME.surface};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 10px;
            }}
        """)
        col2_layout = QVBoxLayout(col2)
        col2_layout.setContentsMargins(14, 14, 14, 14)
        col2_layout.setSpacing(10)

        c2_title = QLabel("WORKSPACES & SECURITY")
        c2_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.05em;")
        col2_layout.addWidget(c2_title)

        self.default_remote_path = QLineEdit(".")
        self.default_remote_path.setStyleSheet("font-family: 'JetBrains Mono', monospace;")
        col2_layout.addWidget(self._make_field("Default Remote Path", self.default_remote_path))

        local_box = QHBoxLayout()
        self.default_local_path = QLineEdit(str(Path.home()))
        self.default_local_path.setStyleSheet("font-family: 'JetBrains Mono', monospace;")
        self.browse_local = QPushButton("Browse")
        self.browse_local.setFixedHeight(28)
        local_box.addWidget(self.default_local_path, 1)
        local_box.addWidget(self.browse_local)
        col2_layout.addWidget(self._make_field("Default Local Workspace", local_box))

        # Persistence Checkboxes
        self.save_profile = QCheckBox("Save profile for quick reconnects")
        self.save_profile.setChecked(True)
        self.remember_secret = QCheckBox("Remember secret in OS keyring (Argon2id Encrypted)")
        self.remember_secret.setChecked(True)

        col2_layout.addWidget(self.save_profile)
        col2_layout.addWidget(self.remember_secret)

        # Advanced FTP/FTPS controls
        self.tls_mode = QComboBox()
        self.tls_mode.addItem("Explicit TLS", "explicit")
        self.tls_mode.addItem("Implicit TLS", "implicit")
        self.verify_tls = QCheckBox("Verify TLS certificate & hostname")
        self.verify_tls.setChecked(True)
        self.passive_mode = QCheckBox("Passive mode")
        self.passive_mode.setChecked(True)
        self.ftp_encoding = QLineEdit("utf-8")
        self.connection_timeout = QLineEdit("30")

        self.environment_notes = QTextEdit()
        self.environment_notes.setPlaceholderText("Notes, hosting panel hints, staging server notes...")
        self.environment_notes.setMaximumHeight(64)
        col2_layout.addWidget(self._make_field("Environment Notes", self.environment_notes))

        col2_layout.addStretch()

        form_row.addWidget(col1, 1)
        form_row.addWidget(col2, 1)

        # 4. Bottom Action Bar
        bottom_bar = QFrame()
        bottom_bar.setObjectName("NewHostBottomBar")
        bottom_bar.setFixedHeight(48)
        bottom_bar.setStyleSheet(f"""
            QFrame#NewHostBottomBar {{
                background-color: {DEFAULT_THEME.surface};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 8px;
                padding: 0 10px;
            }}
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(10, 0, 10, 0)
        bottom_layout.setSpacing(10)

        self.ping_btn = QPushButton("  Test Connection (Ping)")
        self.ping_btn.setIcon(get_icon("sync", size=14))
        self.ping_btn.setFixedHeight(30)
        self.ping_btn.setStyleSheet("""
            QPushButton {
                background: #141418;
                border: 1px solid #1e1e24;
                border-radius: 6px;
                font-size: 11px;
                padding: 0 10px;
                color: #a1a1aa;
            }
            QPushButton:hover {
                background: #1e1e24;
                color: #f4f4f5;
            }
        """)

        self.ping_status_lbl = QLabel("")
        self.ping_status_lbl.setStyleSheet("font-size: 11px; font-weight: 600; background: transparent; border: none;")

        self.protocol_note = QLabel("")
        self.protocol_note.setStyleSheet("font-size: 11px; color: #f59e0b; background: transparent; border: none;")

        self.clear_button = QPushButton("Clear Form")
        self.clear_button.setFixedHeight(30)
        self.clear_button.setStyleSheet("""
            QPushButton {
                background: #141418;
                border: 1px solid #1e1e24;
                border-radius: 6px;
                font-size: 11px;
                padding: 0 12px;
                color: #a1a1aa;
            }
            QPushButton:hover {
                background: #1e1e24;
                color: #f4f4f5;
            }
        """)

        self.connect_button = QPushButton("Connect && Open")
        self.connect_button.setObjectName("PrimaryButton")
        self.connect_button.setFixedHeight(30)
        self.connect_button.setStyleSheet("QPushButton { font-size: 12px; font-weight: 600; padding: 0 16px; }")

        bottom_layout.addWidget(self.ping_btn)
        bottom_layout.addWidget(self.ping_status_lbl)
        bottom_layout.addWidget(self.protocol_note)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.clear_button)
        bottom_layout.addWidget(self.connect_button)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 4px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #27272a;
                border-radius: 2px;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(header_box)
        layout.addWidget(quick_bar)
        layout.addLayout(form_row, 1)
        layout.addWidget(bottom_bar)

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

        # Connections
        self.btn_sftp.clicked.connect(lambda: self._select_protocol("SSH"))
        self.btn_ftps.clicked.connect(lambda: self._select_protocol("FTPS"))
        self.btn_ftp.clicked.connect(lambda: self._select_protocol("FTP"))
        self.btn_rclone.clicked.connect(lambda: self._select_protocol("rclone"))
        self.parse_btn.clicked.connect(self._parse_quick_string)
        self.quick_input.returnPressed.connect(self._parse_quick_string)
        self.auth_type.currentTextChanged.connect(self._sync_auth_fields)
        self.browse_key.clicked.connect(self._browse_key_file)
        self.browse_local.clicked.connect(self._browse_local_folder)
        self.ping_btn.clicked.connect(self._test_ping)
        self.clear_button.clicked.connect(self.clear_form)
        self.connect_button.clicked.connect(self._emit_connect)

        self._select_protocol("SSH")
        self._sync_auth_fields(self.auth_type.currentText())

    def _make_field(self, label: str, widget_or_layout) -> QWidget:  # type: ignore[no-untyped-def]
        holder = QWidget()
        l = QVBoxLayout(holder)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(3)
        caption = QLabel(label)
        caption.setStyleSheet("font-size: 11px; font-weight: 500; color: #a1a1aa; background: transparent; border: none;")
        l.addWidget(caption)
        if isinstance(widget_or_layout, QWidget):
            l.addWidget(widget_or_layout)
        else:
            l.addLayout(widget_or_layout)
        return holder

    def _select_protocol(self, proto: str) -> None:
        self.protocol.setCurrentText(proto)
        if proto in {"SSH", "SFTP"}:
            self.btn_sftp.setChecked(True)
            if self.port.text() in {"", "21", "990"}:
                self.port.setText("22")
            self.protocol_note.setText("")
            self.connect_button.setEnabled(True)
        elif proto == "FTPS":
            self.btn_ftps.setChecked(True)
            if self.port.text() in {"", "22"}:
                self.port.setText("21")
            self.protocol_note.setText("FTPS uses TLS with certificate verification.")
            self.connect_button.setEnabled(True)
        elif proto == "FTP":
            self.btn_ftp.setChecked(True)
            if self.port.text() in {"", "22", "990"}:
                self.port.setText("21")
            self.protocol_note.setText("Warning: FTP transmits unencrypted credentials.")
            self.connect_button.setEnabled(True)
        elif proto == "rclone":
            self.btn_rclone.setChecked(True)
            self.protocol_note.setText("rclone remote profile mode.")
            self.connect_button.setEnabled(False)

    def _parse_quick_string(self) -> None:
        raw = self.quick_input.text().strip()
        if not raw:
            return

        # Matches: ssh -p 2200 user@host
        ssh_match = re.search(r"ssh\s+(?:-p\s+(\d+)\s+)?(?:([a-zA-Z0-9_\-\.]+)\@)?([a-zA-Z0-9_\-\.]+)", raw)
        if ssh_match:
            port = ssh_match.group(1) or "22"
            user = ssh_match.group(2) or ""
            host = ssh_match.group(3) or ""
            self._select_protocol("SSH")
            self.host.setText(host)
            self.port.setText(port)
            if user:
                self.username.setText(user)
            self.profile_name.setText(f"{user}@{host}" if user else host)
            return

        # Matches URL: sftp://user:pass@host:port/path
        try:
            parsed = urlparse(raw if "://" in raw else f"sftp://{raw}")
            if parsed.scheme.upper() in {"SSH", "SFTP", "FTP", "FTPS"}:
                self._select_protocol(parsed.scheme.upper())
            if parsed.hostname:
                self.host.setText(parsed.hostname)
            if parsed.port:
                self.port.setText(str(parsed.port))
            if parsed.username:
                self.username.setText(parsed.username)
            if parsed.password:
                self.secret.setText(parsed.password)
            if parsed.path and parsed.path != "/":
                self.default_remote_path.setText(parsed.path)
            self.profile_name.setText(parsed.hostname or "Parsed Server")
        except Exception:
            pass

    def _test_ping(self) -> None:
        host = self.host.text().strip()
        if not host:
            self.ping_status_lbl.setText("Enter hostname first")
            self.ping_status_lbl.setStyleSheet("font-size: 11px; color: #ef4444;")
            return
        try:
            port = int(self.port.text().strip() or "22")
        except ValueError:
            port = 22

        self.ping_btn.setEnabled(False)
        self.ping_status_lbl.setText("Testing reachability...")
        self.ping_status_lbl.setStyleSheet("font-size: 11px; color: #a1a1aa;")

        self._ping_worker = PingWorker(host, port)
        self._ping_worker.ping_result.connect(self._on_ping_done)
        self._ping_worker.start()

    def _on_ping_done(self, ok: bool, ms: float, message: str) -> None:
        self.ping_btn.setEnabled(True)
        if ok:
            self.ping_status_lbl.setText(f"● {message}")
            self.ping_status_lbl.setStyleSheet("font-size: 11px; color: #10b981; font-weight: 600;")
        else:
            self.ping_status_lbl.setText(f"✕ {message}")
            self.ping_status_lbl.setStyleSheet("font-size: 11px; color: #ef4444; font-weight: 500;")

    def build_request(self) -> dict:
        return build_connection_request(
            protocol=self.protocol.currentText(),
            host=self.host.text(),
            port=self.port.text(),
            username=self.username.text(),
            auth_type=self.auth_type.currentText(),
            secret=self.secret.text(),
            key_path=self.key_path.text(),
            profile_name=self.profile_name.text(),
            save_profile=self.save_profile.isChecked(),
            remember_secret=self.remember_secret.isChecked(),
            default_local_path=self.default_local_path.text(),
            default_remote_path=self.default_remote_path.text(),
            environment_notes=self.environment_notes.toPlainText(),
            connection_options={
                "tls_mode": self.tls_mode.currentData(),
                "verify_tls": self.verify_tls.isChecked(),
                "passive_mode": self.passive_mode.isChecked(),
                "encoding": self.ftp_encoding.text().strip() or "utf-8",
                "timeout": 30.0,
            },
        )

    def focus_host(self) -> None:
        self.host.setFocus()

    def set_connecting(self, host: str, port: int | str) -> None:
        self.status_badge.set_text("Connecting")
        self.status_detail.setText(f"Connecting to {host}:{port}...")
        self.connect_button.setEnabled(False)

    def set_connected(self, profile_name: str, detail: str) -> None:
        self.status_badge.set_text("Connected")
        self.status_detail.setText(f"Connected: {profile_name} ({detail})")
        self.connect_button.setEnabled(True)

    def set_disconnected(self, detail: str = "Configure an SSH/SFTP or FTP/FTPS connection.") -> None:
        self.status_badge.set_text("Ready")
        self.status_detail.setText(detail)
        self.connect_button.setEnabled(True)

    def clear_form(self) -> None:
        self.quick_input.clear()
        self.profile_name.clear()
        self.host.clear()
        self.port.setText("22")
        self.username.clear()
        self.secret.clear()
        self.key_path.clear()
        self.save_profile.setChecked(True)
        self.remember_secret.setChecked(True)
        self.default_local_path.setText(str(Path.home()))
        self.default_remote_path.setText(".")
        self.environment_notes.clear()
        self.ping_status_lbl.clear()
        self._select_protocol("SSH")
        self.auth_type.setCurrentText("Password")
        self.focus_host()

    def _sync_auth_fields(self, auth_type: str) -> None:
        uses_key = auth_type == "SSH Key"
        uses_agent = auth_type == "SSH Agent"
        self.key_path.setEnabled(uses_key)
        self.browse_key.setEnabled(uses_key)
        self.secret.setEnabled(not uses_agent)

    def _browse_key_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH private key",
            str(Path.home() / ".ssh"),
            "SSH private keys (*.pem *.key *.ppk id_*);;All files (*)",
        )
        if path:
            self.key_path.setText(path)
            self.auth_type.setCurrentText("SSH Key")

    def _browse_local_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose default local folder", self.default_local_path.text() or str(Path.home()))
        if path:
            self.default_local_path.setText(path)

    def _emit_connect(self) -> None:
        self.connect_requested.emit(self.build_request())
