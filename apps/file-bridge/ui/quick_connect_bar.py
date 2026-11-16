from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.connections.connection_string import parse_connection_target
from ui.icons import get_icon


class QuickConnectBar(QWidget):
    connect_requested = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.profile_name_label = QLabel("Profile")
        self.profile_name_label.setObjectName("MutedLabel")
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("Profile name")
        self.profile_name.setFixedWidth(130)

        self.protocol = QComboBox()
        self.protocol.addItems(["SFTP", "SSH", "FTP", "FTPS", "rclone"])
        self.protocol.setFixedWidth(85)

        self.host = QLineEdit()
        self.host.setPlaceholderText("user@hostname:port or hostname")
        self.host.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px;")

        self.port = QLineEdit("22")
        self.port.setFixedWidth(54)
        self.port.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px;")

        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.username.setFixedWidth(120)

        self.auth_type = QComboBox()
        self.auth_type.addItems(["Password", "SSH Key", "SSH Agent"])
        self.auth_type.setFixedWidth(105)

        self.password = QLineEdit()
        self.password.setPlaceholderText("Password or passphrase")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setFixedWidth(150)

        self.key_path = QLineEdit()
        self.key_path.setPlaceholderText("Private key path (e.g. ~/.ssh/id_rsa)")
        self.key_browse_button = QPushButton("Browse")
        self.key_browse_button.setFixedHeight(28)

        self.save_profile = QCheckBox("Save")
        self.remember_secret = QCheckBox("Remember")

        self.options_button = QPushButton("Options")
        self.options_button.setIcon(get_icon("settings", size=14))
        self.options_button.setCheckable(True)
        self.options_button.setFixedHeight(28)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("PrimaryButton")
        self.connect_button.setIcon(get_icon("connect", color="#ffffff", size=14))
        self.connect_button.setFixedHeight(28)
        self.connect_button.setMinimumWidth(88)

        # Primary Header Row
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 6, 10, 6)
        main_layout.setSpacing(6)

        primary_row = QHBoxLayout()
        primary_row.setContentsMargins(0, 0, 0, 0)
        primary_row.setSpacing(8)
        primary_row.addWidget(self.protocol)
        primary_row.addWidget(self.host, 1)
        port_label = QLabel("Port")
        port_label.setObjectName("MutedLabel")
        primary_row.addWidget(port_label)
        primary_row.addWidget(self.port)
        primary_row.addWidget(self.options_button)
        primary_row.addWidget(self.connect_button)
        main_layout.addLayout(primary_row)

        # Expandable Drawer for Auth & Profiles
        self.drawer = QFrame()
        self.drawer.setObjectName("ConnectionDrawer")
        self.drawer.setVisible(False)
        drawer_layout = QHBoxLayout(self.drawer)
        drawer_layout.setContentsMargins(8, 6, 8, 6)
        drawer_layout.setSpacing(8)

        user_label = QLabel("User")
        user_label.setObjectName("MutedLabel")
        drawer_layout.addWidget(user_label)
        drawer_layout.addWidget(self.username)

        drawer_layout.addWidget(self.auth_type)

        secret_label = QLabel("Secret")
        secret_label.setObjectName("MutedLabel")
        drawer_layout.addWidget(secret_label)
        drawer_layout.addWidget(self.password)

        key_label = QLabel("Key")
        key_label.setObjectName("MutedLabel")
        drawer_layout.addWidget(key_label)
        drawer_layout.addWidget(self.key_path, 1)
        drawer_layout.addWidget(self.key_browse_button)

        drawer_layout.addWidget(self.profile_name_label)
        drawer_layout.addWidget(self.profile_name)
        drawer_layout.addWidget(self.save_profile)
        drawer_layout.addWidget(self.remember_secret)

        main_layout.addWidget(self.drawer)

        # Signal connections
        self.protocol.currentTextChanged.connect(self._sync_default_port)
        self.save_profile.toggled.connect(self._sync_profile_name_visibility)
        self.key_browse_button.clicked.connect(self._browse_key_file)
        self.connect_button.clicked.connect(self._emit_connect)
        self.options_button.toggled.connect(self.drawer.setVisible)
        self._sync_profile_name_visibility(self.save_profile.isChecked())

    def _sync_default_port(self, protocol: str) -> None:
        if protocol in {"SFTP", "SSH"} and self.port.text() in {"", "21", "990"}:
            self.port.setText("22")
        elif protocol == "FTP":
            self.port.setText("21")
        elif protocol == "FTPS":
            self.port.setText("990")

    def _emit_connect(self) -> None:
        self._apply_connection_target()
        port = self.port.text().strip()
        if not port:
            port = self._default_port_for(self.protocol.currentText())
            self.port.setText(port)
        self.connect_requested.emit(
            {
                "protocol": self.protocol.currentText().lower(),
                "host": self.host.text().strip(),
                "port": port,
                "username": self.username.text().strip(),
                "auth_type": self.auth_type.currentText(),
                "secret": self.password.text(),
                "key_path": self.key_path.text().strip() or None,
                "profile_name": self.profile_name.text().strip() or None,
                "save_profile": self.save_profile.isChecked(),
                "remember_secret": self.remember_secret.isChecked(),
            }
        )

    def _default_port_for(self, protocol: str) -> str:
        if protocol == "FTP":
            return "21"
        if protocol == "FTPS":
            return "990"
        return "22"

    def _apply_connection_target(self) -> None:
        parsed = parse_connection_target(self.host.text())
        if parsed is None:
            return
        if parsed.protocol:
            protocol = parsed.protocol.upper()
            if protocol in {"SSH", "SFTP"}:
                self.protocol.setCurrentText(protocol)
        if parsed.host:
            self.host.setText(parsed.host)
        if parsed.username and not self.username.text().strip():
            self.username.setText(parsed.username)
        if parsed.port:
            self.port.setText(str(parsed.port))

    def _sync_profile_name_visibility(self, checked: bool) -> None:
        self.profile_name_label.setVisible(checked)
        self.profile_name.setVisible(checked)

    def _browse_key_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select SSH private key",
            "",
            "SSH private keys (*.pem *.key *.ppk id_*);;PEM files (*.pem);;All files (*)",
        )
        if path:
            self.key_path.setText(path)
            self.auth_type.setCurrentText("SSH Key")
