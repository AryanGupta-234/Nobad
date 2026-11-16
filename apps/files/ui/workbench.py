from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QScrollArea,
    QStyle,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.workbench_models import (
    ConnectionCommandState,
    FilePaneMode,
    NavigationItem,
    ResponsiveBreakpoint,
    build_connection_request,
    default_navigation_items,
    pane_mode_for_breakpoint,
)
from ui.branding import application_icon


from ui.icons import get_icon


USER_ROLE_PROFILE = int(Qt.ItemDataRole.UserRole)


def _standard_icon(widget: QWidget, icon_name: str):
    icon = get_icon(icon_name)
    if not icon.isNull():
        return icon
    names = {
        "connections": "SP_DriveNetIcon",
        "credentials": "SP_DialogPasswordIcon",
        "files": "SP_DirIcon",
        "dashboard": "SP_FileDialogDetailedView",
        "services": "SP_FileDialogDetailedView",
        "tunnels": "SP_FileDialogDetailedView",
        "activity": "SP_FileDialogDetailedView",
        "transfers": "SP_FileDialogDetailedView",
        "terminal": "SP_ComputerIcon",
        "editor": "SP_FileIcon",
        "logs": "SP_MessageBoxInformation",
        "settings": "SP_FileDialogContentsView",
        "sync": "SP_BrowserReload",
        "deploy": "SP_ArrowUp",
        "playbooks": "SP_MediaPlay",
        "connect": "SP_DialogApplyButton",
        "disconnect": "SP_DialogCloseButton",
        "drawer": "SP_TitleBarShadeButton",
        "folder": "SP_DirOpenIcon",
        "copy": "SP_FileDialogNewFolder",
    }
    enum_name = names.get(icon_name, "SP_FileIcon")
    pixmap = getattr(QStyle.StandardPixmap, enum_name, QStyle.StandardPixmap.SP_FileIcon)
    return widget.style().standardIcon(pixmap)


class StatusBadge(QFrame):
    def __init__(self, text: str = "Ready", *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBadge")
        self.setStyleSheet("QFrame#StatusBadge { background: transparent; border: none; }")
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #71717a; font-size: 10px; margin-right: 2px; background: transparent; border: none;")
        self.label = QLabel(text)
        self.label.setObjectName("MutedLabel")
        self.label.setStyleSheet("background: transparent; border: none; font-size: 11px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.dot)
        layout.addWidget(self.label)

    def set_text(self, text: str, state: str = "default") -> None:
        self.label.setText(text)
        if text.lower() == "connected":
            self.dot.setStyleSheet("color: #10b981; font-size: 10px; margin-right: 2px; background: transparent; border: none;")
            self.label.setStyleSheet("color: #10b981; font-weight: 600; background: transparent; border: none;")
        elif text.lower() in {"connecting", "disconnecting"}:
            self.dot.setStyleSheet("color: #f59e0b; font-size: 10px; margin-right: 2px; background: transparent; border: none;")
            self.label.setStyleSheet("color: #f59e0b; font-weight: 500; background: transparent; border: none;")
        else:
            self.dot.setStyleSheet("color: #71717a; font-size: 10px; margin-right: 2px; background: transparent; border: none;")
            self.label.setStyleSheet("color: #a1a1aa; background: transparent; border: none;")


class ConnectionStatusBar(QFrame):
    disconnect_requested = Signal()
    palette_requested = Signal()
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ConnectionStatusBar")
        self.setFixedHeight(48)
        self.setStyleSheet("""
            QFrame#ConnectionStatusBar {
                background-color: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
        """)

        # Left Brand
        brand_box = QHBoxLayout()
        brand_box.setContentsMargins(0, 0, 0, 0)
        brand_box.setSpacing(8)

        logo = QLabel()
        logo.setFixedSize(26, 26)
        logo.setStyleSheet("background: transparent; border: none;")
        logo.setPixmap(application_icon().pixmap(24, 24))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Remote File Manager")
        title.setStyleSheet("font-size: 13px; font-weight: 600; color: #f4f4f5; background: transparent; border: none;")
        brand_box.addWidget(logo)
        brand_box.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setFixedHeight(18)
        sep.setStyleSheet("background-color: #1e1e24; border: none;")

        # Quick Connect Status Pill
        self.status_pill = QFrame()
        self.status_pill.setObjectName("TopStatusPill")
        self.status_pill.setFixedHeight(26)
        self.status_pill.setStyleSheet("""
            QFrame#TopStatusPill {
                background-color: #141418;
                border: 1px solid #1e1e24;
                border-radius: 6px;
                padding: 0;
            }
        """)
        pill_layout = QHBoxLayout(self.status_pill)
        pill_layout.setContentsMargins(4, 0, 8, 0)
        pill_layout.setSpacing(6)
        pill_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.protocol_badge = QLabel("SFTP")
        self.protocol_badge.setFixedHeight(18)
        self.protocol_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.protocol_badge.setStyleSheet("""
            background: rgba(99, 102, 241, 0.15);
            color: #818cf8;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            font-size: 10px;
            padding: 0 5px;
            border-radius: 4px;
            border: none;
        """)

        self.detail = QLabel("No server connected")
        self.detail.setStyleSheet("background: transparent; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #a1a1aa; border: none;")

        self.status_badge = StatusBadge("Ready")

        pill_layout.addWidget(self.protocol_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        pill_layout.addWidget(self.detail, 0, Qt.AlignmentFlag.AlignVCenter)
        pill_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Right Action Buttons
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("DangerButton")
        self.disconnect_button.setToolTip("Disconnect the active File Manager connection")
        self.disconnect_button.setFixedHeight(28)
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.setVisible(False)

        # Single Unified Command Palette Trigger
        self.palette_button = QPushButton("   Command Palette")
        self.palette_button.setIcon(get_icon("search", color="#a1a1aa", size=13))
        self.palette_button.setFixedHeight(28)
        self.palette_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.palette_button.setStyleSheet("""
            QPushButton {
                background-color: #141418;
                border: 1px solid #1e1e24;
                border-radius: 6px;
                color: #a1a1aa;
                font-size: 11px;
                padding: 0 10px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #1a1a20;
                color: #f4f4f5;
                border-color: #27272a;
            }
        """)
        kbd_badge = QLabel("Ctrl+K")
        kbd_badge.setStyleSheet("""
            background: #111114;
            border: 1px solid #1e1e24;
            border-radius: 4px;
            color: #71717a;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            padding: 1px 5px;
        """)
        palette_box = QHBoxLayout()
        palette_box.setContentsMargins(0, 0, 0, 0)
        palette_box.setSpacing(6)
        palette_box.addWidget(self.palette_button)
        palette_box.addWidget(kbd_badge)

        self.settings_button = QPushButton()
        self.settings_button.setIcon(get_icon("settings", color="#a1a1aa", size=15))
        self.settings_button.setFixedSize(28, 28)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setStyleSheet("""
            QPushButton {
                background-color: #141418;
                border: 1px solid #1e1e24;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1a1a20;
                border-color: #27272a;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)
        layout.addLayout(brand_box)
        layout.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch()
        layout.addWidget(self.disconnect_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(palette_box)
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.palette_button.clicked.connect(self.palette_requested.emit)
        self.settings_button.clicked.connect(self.settings_requested.emit)

    def set_connecting(self, host: str, port: int | str) -> None:
        self.status_badge.set_text("Connecting")
        self.detail.setText(f"{host}:{port}")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.setVisible(False)

    def set_connected(self, profile_name: str, detail: str) -> None:
        self.status_badge.set_text("Connected")
        # Extract protocol if present in detail, e.g. "SFTP user@host:22"
        parts = detail.split(maxsplit=1)
        if len(parts) == 2 and parts[0].upper() in {"SFTP", "SSH", "FTP", "FTPS"}:
            self.protocol_badge.setText(parts[0].upper())
            self.detail.setText(parts[1])
        else:
            self.detail.setText(f"{profile_name} ({detail})")
        self.disconnect_button.setEnabled(True)
        self.disconnect_button.setVisible(True)

    def set_disconnecting(self, profile_name: str) -> None:
        self.status_badge.set_text("Disconnecting")
        self.detail.setText(profile_name)
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.setVisible(False)

    def set_disconnected(self, detail: str = "No server connected") -> None:
        self.status_badge.set_text("Ready")
        self.protocol_badge.setText("SFTP")
        self.detail.setText(detail)
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.setVisible(False)


class EmptyState(QWidget):
    def __init__(self, title: str, message: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        body = QLabel(message)
        body.setObjectName("MutedLabel")
        body.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(8)
        layout.addStretch()
        layout.addWidget(heading, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(body, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()


class ActionToolbar(QFrame):
    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PanelHeader")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 8, 10, 8)
        self.layout.setSpacing(8)

    def add_button(self, text: str, icon_name: str | None = None, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if icon_name:
            button.setIcon(_standard_icon(self, icon_name))
        if primary:
            button.setObjectName("PrimaryButton")
        self.layout.addWidget(button)
        return button

    def add_stretch(self) -> None:
        self.layout.addStretch()


class PathBar(QFrame):
    path_changed = Signal(str)

    def __init__(self, label: str, default_path: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PanelHeader")
        self.title = QLabel(label)
        self.title.setObjectName("MutedLabel")
        self.path = QLineEdit(default_path)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.title)
        layout.addWidget(self.path, 1)
        self.path.returnPressed.connect(lambda: self.path_changed.emit(self.path.text()))


class ResponsiveStackedWidget(QStackedWidget):
    """
    QStackedWidget that reports sizeHint and minimumSizeHint based on the
    CURRENTLY ACTIVE page rather than the maximum union of all 15 pages.
    This prevents hidden, complex tabs from artificially expanding the window.
    """
    def sizeHint(self) -> QSize:
        cur = self.currentWidget()
        if cur is not None:
            return cur.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        cur = self.currentWidget()
        if cur is not None:
            return cur.minimumSizeHint()
        return super().minimumSizeHint()


class NavigationRail(QFrame):
    section_selected = Signal(str)

    def __init__(self, items: list[NavigationItem] | None = None) -> None:
        super().__init__()
        self.setObjectName("NavigationRail")
        self._items = items or default_navigation_items()
        self._buttons: dict[str, QToolButton] = {}
        self._group_labels: list[QLabel] = []
        self._collapsed = True

        self.setFixedWidth(60)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        rail_layout = QVBoxLayout(self)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(0)

        # Frameless, smooth scroll area so navigation rail can shrink to any window height
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._add_group(layout, "Primary", "primary")
        layout.addSpacing(6)
        self._add_group(layout, "Coming Soon", "coming_soon")
        layout.addStretch()

        self.scroll_area.setWidget(container)
        rail_layout.addWidget(self.scroll_area, 1)

        self.set_current_section("Files")

    def set_current_section(self, section: str) -> None:
        button = self._buttons.get(section)
        if button is not None:
            button.setChecked(True)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = True
        self.setFixedWidth(60)
        for key, button in self._buttons.items():
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setText("")
            button.setFixedSize(44, 40)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _add_group(self, layout: QVBoxLayout, title: str, group: str) -> None:
        items = [entry for entry in self._items if entry.group == group]
        if not items:
            return
        for item in items:
            button = QToolButton()
            button.setObjectName("NavButton")
            button.setText(item.title)
            button.setToolTip(item.title)
            button.setCheckable(True)
            button.setEnabled(item.enabled)
            button.setIcon(_standard_icon(self, item.icon_name))
            button.setFixedSize(44, 40)
            button.setIconSize(QSize(20, 20))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setStyleSheet("""
                QToolButton#NavButton {
                    border: 1px solid transparent;
                    border-radius: 8px;
                    padding: 6px;
                    background: transparent;
                }
                QToolButton#NavButton:hover {
                    background: #222328;
                }
                QToolButton#NavButton:checked {
                    background: #18181b;
                    border: 1px solid #27272a;
                }
            """)
            button.clicked.connect(lambda _checked=False, key=item.key: self.section_selected.emit(key))
            self.button_group.addButton(button)
            self._buttons[item.key] = button
            layout.addWidget(button)

    def _title_for(self, key: str) -> str:
        for item in self._items:
            if item.key == key:
                return item.title
        return key


class ConnectionDrawer(QFrame):
    connect_requested = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ConnectionDrawer")
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("Production server")
        self.protocol = QComboBox()
        self.protocol.addItems(["SFTP", "SSH", "FTP", "FTPS", "rclone"])
        self.host = QLineEdit()
        self.host.setPlaceholderText("ssh ubuntu@example.com or host")
        self.port = QLineEdit("22")
        self.port.setMaximumWidth(96)
        self.username = QLineEdit()
        self.username.setPlaceholderText("username")
        self.auth_type = QComboBox()
        self.auth_type.addItems(["Password", "SSH Key", "SSH Agent"])
        self.secret = QLineEdit()
        self.secret.setPlaceholderText("password or key passphrase")
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_path = QLineEdit()
        self.key_path.setPlaceholderText("local private key path (.pem, id_rsa, .key)")
        self.browse_key = QPushButton("Browse")
        self.save_profile = QCheckBox("Save profile")
        self.remember_secret = QCheckBox("Remember secret")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("PrimaryButton")

        layout = QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)
        self._add_field(layout, 0, 0, "Name", self.profile_name)
        self._add_field(layout, 0, 1, "Protocol", self.protocol)
        self._add_field(layout, 0, 2, "Host", self.host)
        self._add_field(layout, 0, 3, "Port", self.port)
        self._add_field(layout, 1, 0, "User", self.username)
        self._add_field(layout, 1, 1, "Auth", self.auth_type)
        self._add_field(layout, 1, 2, "Secret", self.secret)
        key_holder = QWidget()
        key_layout = QHBoxLayout(key_holder)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(6)
        key_layout.addWidget(self.key_path, 1)
        key_layout.addWidget(self.browse_key)
        self._add_field(layout, 1, 3, "Key", key_holder)
        actions = QHBoxLayout()
        actions.addWidget(self.save_profile)
        actions.addWidget(self.remember_secret)
        actions.addStretch()
        actions.addWidget(self.connect_button)
        layout.addLayout(actions, 2, 0, 1, 4)

        self.protocol.currentTextChanged.connect(self._sync_default_port)
        self.browse_key.clicked.connect(self._browse_key_file)
        self.connect_button.clicked.connect(self._emit_connect)

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
        )

    def focus_host(self) -> None:
        self.host.setFocus()

    def _emit_connect(self) -> None:
        self.connect_requested.emit(self.build_request())

    def _sync_default_port(self, protocol: str) -> None:
        if protocol in {"SFTP", "SSH"} and self.port.text() in {"", "21", "990"}:
            self.port.setText("22")
        elif protocol == "FTP":
            self.port.setText("21")
        elif protocol == "FTPS":
            self.port.setText("990")

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

    def _add_field(self, layout: QGridLayout, row: int, column: int, label: str, widget: QWidget) -> None:
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(3)
        caption = QLabel(label)
        caption.setObjectName("MutedLabel")
        holder_layout.addWidget(caption)
        holder_layout.addWidget(widget)
        layout.addWidget(holder, row, column)


class ConnectionCommandBar(QFrame):
    connect_requested = Signal(dict)
    saved_profile_requested = Signal(object)
    disconnect_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ConnectionCommandBar")
        self._state = ConnectionCommandState()
        self._profiles: list[object] = []
        self.title = QLabel("Remote File Manager")
        self.title.setObjectName("PageTitle")
        self.status_badge = StatusBadge("Ready")
        self.detail = QLabel("No server connected")
        self.detail.setObjectName("MutedLabel")
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.addItem("Quick connect", None)
        self.drawer_button = QPushButton("Connection Details")
        self.drawer_button.setIcon(_standard_icon(self, "drawer"))
        self.connect_button = QPushButton("Connect")
        self.connect_button.setIcon(_standard_icon(self, "connect"))
        self.connect_button.setObjectName("PrimaryButton")
        self.drawer = ConnectionDrawer()
        self.drawer.setVisible(False)

        top = QHBoxLayout()
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(10)
        top.addWidget(self.title)
        top.addWidget(self.status_badge)
        top.addWidget(self.detail, 1)
        top.addWidget(self.profile_combo)
        top.addWidget(self.drawer_button)
        top.addWidget(self.connect_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(self.drawer)

        self.drawer.connect_requested.connect(self.connect_requested)
        self.drawer_button.clicked.connect(self.toggle_drawer)
        self.connect_button.clicked.connect(self._connect_or_disconnect)

    def set_profiles(self, profiles: list[object]) -> None:
        current_id = self._current_profile_id()
        self._profiles = profiles
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("Quick connect", None)
        for profile in profiles:
            label = getattr(profile, "name", "Unnamed")
            host = getattr(profile, "host", "")
            user = getattr(profile, "username", "")
            self.profile_combo.addItem(f"{label}  {user}@{host}", profile)
        if current_id:
            for index in range(self.profile_combo.count()):
                profile = self.profile_combo.itemData(index, USER_ROLE_PROFILE)
                if getattr(profile, "id", None) == current_id:
                    self.profile_combo.setCurrentIndex(index)
                    break
        self.profile_combo.blockSignals(False)

    def set_state(self, state: ConnectionCommandState) -> None:
        self._state = state
        self.status_badge.set_text(state.status)
        self.detail.setText(state.detail)
        if state.connected:
            self.connect_button.setText("Disconnect")
            self.connect_button.setIcon(_standard_icon(self, "disconnect"))
        else:
            self.connect_button.setText("Connect")
            self.connect_button.setIcon(_standard_icon(self, "connect"))
        self.connect_button.setEnabled(not state.connecting)
        self.profile_combo.setEnabled(not state.connecting and not state.connected)
        self.drawer_button.setEnabled(not state.connecting and not state.connected)

    def set_connecting(self, host: str, port: int | str) -> None:
        self.set_state(ConnectionCommandState("Connecting", f"{host}:{port}", connecting=True))

    def set_connected(self, profile_name: str, detail: str) -> None:
        self.set_state(ConnectionCommandState("Connected", f"{profile_name}  {detail}", connected=True))
        self.drawer.setVisible(False)

    def set_disconnected(self, detail: str = "No server connected") -> None:
        self.set_state(ConnectionCommandState("Ready", detail))

    def toggle_drawer(self) -> None:
        expanded = not self.drawer.isVisible()
        self.drawer.setVisible(expanded)
        if expanded:
            self.drawer.focus_host()

    def selected_profile(self):  # type: ignore[no-untyped-def]
        return self.profile_combo.currentData(USER_ROLE_PROFILE)

    def _connect_or_disconnect(self) -> None:
        if self._state.connected:
            self.disconnect_requested.emit()
            return
        profile = self.selected_profile()
        if profile is not None and not self.drawer.isVisible():
            self.saved_profile_requested.emit(profile)
            return
        if not self.drawer.isVisible():
            self.drawer.setVisible(True)
            self.drawer.focus_host()
            return
        self.connect_requested.emit(self.drawer.build_request())

    def _current_profile_id(self) -> str | None:
        profile = self.selected_profile()
        return getattr(profile, "id", None)


class ResponsiveFileManager(QWidget):
    def __init__(self, local_panel: QWidget, remote_panel: QWidget) -> None:
        super().__init__()
        self.local_panel = local_panel
        self.remote_panel = remote_panel
        self._preferred_single = FilePaneMode.LOCAL
        self.breakpoint = ResponsiveBreakpoint.WIDE
        self.title = QLabel("Files")
        self.title.setObjectName("PageTitle")
        self.status = QLabel("Browse local and remote files side by side.")
        self.status.setObjectName("MutedLabel")
        self.local_toggle = QPushButton("Local")
        self.local_toggle.setCheckable(True)
        self.remote_toggle = QPushButton("Remote")
        self.remote_toggle.setCheckable(True)
        self.local_toggle.setChecked(True)
        self.toggle_group = QButtonGroup(self)
        self.toggle_group.setExclusive(True)
        self.toggle_group.addButton(self.local_toggle)
        self.toggle_group.addButton(self.remote_toggle)
        self.toggle_bar = QWidget()
        toggle_layout = QHBoxLayout(self.toggle_bar)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.addWidget(self.local_toggle)
        toggle_layout.addWidget(self.remote_toggle)

        self.header = QFrame()
        self.header.setObjectName("PanelHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.addWidget(self.title)
        header_layout.addWidget(self.status, 1)
        header_layout.addWidget(self.toggle_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(local_panel)
        self.splitter.addWidget(remote_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.splitter, 1)

        self.local_toggle.clicked.connect(lambda: self.set_pane_mode(FilePaneMode.LOCAL))
        self.remote_toggle.clicked.connect(lambda: self.set_pane_mode(FilePaneMode.REMOTE))
        self.set_breakpoint(ResponsiveBreakpoint.WIDE)

    def set_breakpoint(self, breakpoint: ResponsiveBreakpoint) -> None:
        self.breakpoint = breakpoint
        mode = pane_mode_for_breakpoint(breakpoint, self._preferred_single)
        self._apply_mode(mode)

    def set_pane_mode(self, mode: FilePaneMode) -> None:
        if mode in {FilePaneMode.LOCAL, FilePaneMode.REMOTE}:
            self._preferred_single = mode
        self._apply_mode(pane_mode_for_breakpoint(self.breakpoint, mode))

    def pane_mode(self) -> FilePaneMode:
        if self.local_panel.isVisible() and self.remote_panel.isVisible():
            return FilePaneMode.DUAL
        if self.remote_panel.isVisible():
            return FilePaneMode.REMOTE
        return FilePaneMode.LOCAL

    def set_remote_active(self) -> None:
        self._preferred_single = FilePaneMode.REMOTE
        if self.breakpoint == ResponsiveBreakpoint.NARROW:
            self._apply_mode(FilePaneMode.REMOTE)

    def _apply_mode(self, mode: FilePaneMode) -> None:
        dual = mode == FilePaneMode.DUAL
        self.header.setVisible(not dual)
        self.toggle_bar.setVisible(not dual)
        self.local_panel.setVisible(dual or mode == FilePaneMode.LOCAL)
        self.remote_panel.setVisible(dual or mode == FilePaneMode.REMOTE)
        self.local_toggle.setChecked(mode != FilePaneMode.REMOTE)
        self.remote_toggle.setChecked(mode == FilePaneMode.REMOTE)


class BottomDockPanel(QFrame):
    tab_changed = Signal(str)
    clear_finished_requested = Signal()
    open_terminal_requested = Signal()

    def __init__(self, transfer_panel: QWidget, logs_panel: QWidget, terminal_panel: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("BottomDockPanel")
        self.transfer_panel = transfer_panel
        self.terminal_panel = terminal_panel
        self.logs_panel = logs_panel

        self.setStyleSheet("""
            QFrame#BottomDockPanel {
                background-color: #111114;
                border: 0;
                border-top: 1px solid #1e1e24;
            }
        """)

        # Tab Bar Header
        header = QFrame()
        header.setObjectName("DockHeader")
        header.setFixedHeight(34)
        header.setStyleSheet("""
            QFrame#DockHeader {
                background-color: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(6)

        # Tab buttons
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)

        self.transfers_btn = QPushButton("Active Transfers")
        self.transfers_btn.setCheckable(True)
        self.transfers_btn.setChecked(True)
        self.transfers_btn.setIcon(get_icon("activity", color="#818cf8", size=14))

        # self.terminal_btn = QPushButton("Terminal Studio ↗")
        # self.terminal_btn.setIcon(get_icon("terminal", color="#a1a1aa", size=14))

        self.logs_btn = QPushButton("Logs && Diagnostics")
        self.logs_btn.setCheckable(True)
        self.logs_btn.setIcon(get_icon("code", color="#a1a1aa", size=14))

        # for btn in (self.transfers_btn, self.terminal_btn, self.logs_btn):
        for btn in (self.transfers_btn, self.logs_btn):
            btn.setObjectName("DockTabButton")
            btn.setFixedHeight(28)
            btn.setStyleSheet("""
                QPushButton#DockTabButton {
                    background: transparent;
                    border: 0;
                    border-bottom: 2px solid transparent;
                    color: #a1a1aa;
                    font-size: 12px;
                    font-weight: 500;
                    padding: 0 14px;
                    min-width: 130px;
                }
                QPushButton#DockTabButton:hover {
                    color: #f4f4f5;
                }
                QPushButton#DockTabButton:checked {
                    color: #818cf8;
                    border-bottom: 2px solid #6366f1;
                    font-weight: 600;
                }
            """)
            self.tab_group.addButton(btn)
            header_layout.addWidget(btn)

        header_layout.addStretch()

        # Bandwidth Speed & Clear Finished
        self.bandwidth_label = QLabel("▲ 0.0 KB/s")
        self.bandwidth_label.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #10b981; font-weight: 600;")
        header_layout.addWidget(self.bandwidth_label)

        self.clear_btn = QPushButton("Clear Finished")
        self.clear_btn.setFixedHeight(24)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: #141418;
                border: 1px solid #1e1e24;
                border-radius: 4px;
                color: #a1a1aa;
                font-size: 11px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background: #1e1e24;
                color: #f4f4f5;
            }
        """)
        header_layout.addWidget(self.clear_btn)

        # Stacked pages
        self.pages = QStackedWidget()
        self.pages.addWidget(self.transfer_panel)
        if self.terminal_panel is not None:
            self.pages.addWidget(self.terminal_panel)
        self.pages.addWidget(self.logs_panel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.pages, 1)

        self.transfers_btn.clicked.connect(lambda: self.select_tab("Active Transfers"))
        # self.terminal_btn.clicked.connect(self._on_terminal_clicked
        self.logs_btn.clicked.connect(lambda: self.select_tab("Logs & Diagnostics"))
        self.clear_btn.clicked.connect(self.clear_finished_requested.emit)

    def _on_terminal_clicked(self) -> None:
        if self.terminal_panel is not None:
            self.select_tab("Embedded Terminal")
        else:
            self.open_terminal_requested.emit()

    def select_tab(self, name: str) -> None:
        if name in {"Active Transfers", "Transfers"}:
            self.transfers_btn.setChecked(True)
            self.pages.setCurrentWidget(self.transfer_panel)
        elif name in {"Embedded Terminal", "Terminal"}:
            if self.terminal_panel is not None:
                # self.terminal_btn.setChecked(True)
                self.pages.setCurrentWidget(self.terminal_panel)
            else:
                self.open_terminal_requested.emit()
                return
        elif name in {"Logs & Diagnostics", "Logs"}:
            self.logs_btn.setChecked(True)
            self.pages.setCurrentWidget(self.logs_panel)
        self.tab_changed.emit(name)

    def open_tab(self, name: str) -> None:
        self.select_tab(name)

    def active_tab(self) -> str:
        if self.pages.currentWidget() == self.terminal_panel:
            return "Embedded Terminal"
        if self.pages.currentWidget() == self.logs_panel:
            return "Logs & Diagnostics"
        return "Active Transfers"

    def set_transfer_count(self, count: int) -> None:
        self.transfers_btn.setText(f"Active Transfers ({count})" if count > 0 else "Active Transfers")

    def set_bandwidth(self, text: str) -> None:
        self.bandwidth_label.setText(text)


class WorkbenchMainView(QWidget):
    def __init__(self, file_manager: ResponsiveFileManager, bottom_dock: BottomDockPanel) -> None:
        super().__init__()
        self.file_manager = file_manager
        self.bottom_dock = bottom_dock

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(file_manager)
        self.splitter.addWidget(bottom_dock)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([550, 190])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)


class ActivityPage(QFrame):
    def __init__(self, transfer_panel: QWidget, logs_panel: QWidget) -> None:
        super().__init__()
        self.setObjectName("ActivityPage")
        self.tabs = QTabWidget()
        self.tabs.addTab(transfer_panel, "Transfers")
        self.tabs.addTab(logs_panel, "Logs")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs, 1)

    def open_tab(self, title: str) -> None:
        self._select_tab(title)

    def active_tab(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())

    def _select_tab(self, title: str) -> bool:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == title:
                self.tabs.setCurrentIndex(index)
                return True
        return False


class WorkbenchPage(QWidget):
    def __init__(self, title: str, subtitle: str, content: QWidget) -> None:
        super().__init__()
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        body = QLabel(subtitle)
        body.setObjectName("MutedLabel")
        body.setWordWrap(True)
        header = QFrame()
        header.setObjectName("PanelHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(4)
        header_layout.addWidget(heading)
        header_layout.addWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(header)
        layout.addWidget(content, 1)


class ComingSoonPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        deploy = EmptyState("Deployments", "Deployment helpers remain discoverable without crowding the active file-transfer workflow.")
        stack = QStackedWidget()
        stack.addWidget(deploy)
        self.switcher = QComboBox()
        self.switcher.addItems(["Deployments"])
        self.switcher.currentIndexChanged.connect(stack.setCurrentIndex)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.switcher)
        layout.addWidget(stack, 1)


class OperationDetailsDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        message: str,
        details: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 320)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        body = QLabel(message)
        body.setWordWrap(True)
        self.details = QTextEdit(details or "")
        self.details.setReadOnly(True)
        self.details.setVisible(bool(details))
        close = QPushButton("Close")
        close.setObjectName("PrimaryButton")
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addWidget(self.details, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)


def make_icon_action(parent: QWidget, text: str, icon_name: str) -> QAction:
    action = QAction(_standard_icon(parent, icon_name), text, parent)
    return action
