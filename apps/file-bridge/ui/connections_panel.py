from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.connections.profile import ConnectionProfile
from ui.icons import get_icon
from ui.theme import DEFAULT_THEME


class ServerCardWidget(QFrame):
    connect_requested = Signal(object)
    edit_requested = Signal(object)
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)

    def __init__(self, profile: ConnectionProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.setObjectName("ServerCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame#ServerCard {{
                background-color: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 10px;
                padding: 12px;
            }}
            QFrame#ServerCard:hover {{
                border-color: #3f3f46;
                background-color: #1c1c20;
            }}
        """)

        # Top row: Icon + Name + Active badge
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setStyleSheet(f"""
            background: rgba(99, 102, 241, 0.1);
            border: 1px solid rgba(99, 102, 241, 0.2);
            border-radius: 8px;
            padding: 6px;
        """)
        icon_lbl.setPixmap(get_icon("servers", color=DEFAULT_THEME.accent, size=20).pixmap(20, 20))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        name_lbl = QLabel(profile.name)
        name_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #f4f4f5;")
        endpoint_lbl = QLabel(f"{profile.username}@{profile.host}:{profile.port}")
        endpoint_lbl.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #a1a1aa;")

        title_box.addWidget(name_lbl)
        title_box.addWidget(endpoint_lbl)

        # Status badge (standby or ready)
        status_badge = QLabel("● Ready")
        status_badge.setStyleSheet("font-size: 10px; font-weight: 500; color: #71717a; padding: 2px 6px; background: #121215; border-radius: 4px;")

        top_layout.addWidget(icon_lbl)
        top_layout.addLayout(title_box, 1)
        top_layout.addWidget(status_badge)

        # Middle row: Protocol & Auth badges
        badge_layout = QHBoxLayout()
        badge_layout.setContentsMargins(0, 8, 0, 8)
        badge_layout.setSpacing(6)

        proto = profile.protocol.value.upper()
        proto_badge = QLabel(proto)
        proto_color = "#818cf8" if proto in {"SFTP", "SSH"} else "#10b981"
        proto_bg = "rgba(99, 102, 241, 0.15)" if proto in {"SFTP", "SSH"} else "rgba(16, 185, 129, 0.15)"
        proto_badge.setStyleSheet(f"""
            background: {proto_bg};
            color: {proto_color};
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
        """)

        auth_badge = QLabel(profile.auth_type.value)
        auth_badge.setStyleSheet(f"""
            background: {DEFAULT_THEME.surface};
            border: 1px solid {DEFAULT_THEME.border};
            color: #a1a1aa;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
        """)

        sec_text = "OS Keyring" if (profile.password_secret_ref or profile.ssh_private_key_passphrase_secret_ref) else "Prompt Auth"
        sec_badge = QLabel(sec_text)
        sec_badge.setStyleSheet(f"""
            background: {DEFAULT_THEME.surface};
            border: 1px solid {DEFAULT_THEME.border};
            color: #71717a;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
        """)

        badge_layout.addWidget(proto_badge)
        badge_layout.addWidget(auth_badge)
        badge_layout.addWidget(sec_badge)
        badge_layout.addStretch()

        # Bottom row: Action Buttons
        bot_layout = QHBoxLayout()
        bot_layout.setContentsMargins(0, 4, 0, 0)
        bot_layout.setSpacing(6)

        remote_path = profile.default_remote_path or "."
        path_hint = QLabel(f"Path: {remote_path}")
        path_hint.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #71717a;")

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("PrimaryButton")
        self.connect_btn.setFixedHeight(26)
        self.connect_btn.setStyleSheet("""
            QPushButton#PrimaryButton {
                font-size: 11px;
                padding: 0 10px;
            }
        """)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setFixedHeight(26)
        self.edit_btn.setStyleSheet("font-size: 11px; padding: 0 8px;")

        self.delete_btn = QPushButton("✕")
        self.delete_btn.setFixedHeight(26)
        self.delete_btn.setToolTip("Delete connection profile")
        self.delete_btn.setStyleSheet("font-size: 11px; padding: 0 8px; color: #ef4444;")

        bot_layout.addWidget(path_hint)
        bot_layout.addStretch()
        bot_layout.addWidget(self.delete_btn)
        bot_layout.addWidget(self.edit_btn)
        bot_layout.addWidget(self.connect_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)
        layout.addLayout(top_layout)
        layout.addLayout(badge_layout)
        layout.addLayout(bot_layout)

        self.connect_btn.clicked.connect(lambda: self.connect_requested.emit(self.profile))
        self.edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.profile))
        self.delete_btn.clicked.connect(self._confirm_delete)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().mouseDoubleClickEvent(event)
        self.connect_requested.emit(self.profile)

    def _confirm_delete(self) -> None:
        response = QMessageBox.question(
            self,
            "Delete saved profile",
            f"Delete saved profile '{self.profile.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(self.profile.id)


class ConnectionsPanel(QWidget):
    connect_requested = Signal(object)
    edit_requested = Signal(object)
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)
    new_connection_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._profiles: list[ConnectionProfile] = []
        self._filter_text: str = ""
        self._protocol_filter: str = "ALL"
        self._view_mode: str = "grid"

        # 1. Top Section Header
        header_box = QHBoxLayout()
        header_box.setContentsMargins(0, 0, 0, 0)
        header_box.setSpacing(10)

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        page_title = QLabel("Saved Server Connections")
        page_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f4f4f5; letter-spacing: -0.02em;")
        page_subtitle = QLabel("Organize, monitor, and one-click reconnect to remote infrastructure")
        page_subtitle.setStyleSheet("font-size: 12px; color: #71717a;")

        title_layout.addWidget(page_title)
        title_layout.addWidget(page_subtitle)

        self.new_btn = QPushButton("+ New Connection")
        self.new_btn.setObjectName("PrimaryButton")
        self.new_btn.setFixedHeight(30)
        self.new_btn.setStyleSheet("QPushButton { font-size: 12px; font-weight: 600; padding: 0 12px; }")

        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(get_icon("sync", size=14))
        self.refresh_button.setToolTip("Reload profiles")
        self.refresh_button.setFixedSize(30, 30)

        header_box.addLayout(title_layout, 1)
        header_box.addWidget(self.refresh_button)
        header_box.addWidget(self.new_btn)

        # 2. Modern Filter & Controls Bar
        filter_bar = QFrame()
        filter_bar.setObjectName("FilterBar")
        filter_bar.setStyleSheet(f"""
            QFrame#FilterBar {{
                background-color: {DEFAULT_THEME.surface};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 8px;
                padding: 4px 8px;
            }}
        """)
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(6, 4, 6, 4)
        filter_layout.setSpacing(8)

        search_icon = QLabel()
        search_icon.setPixmap(get_icon("search", color="#71717a", size=14).pixmap(14, 14))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search servers by name, IP, or user...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: 0;
                color: #f4f4f5;
                font-size: 12px;
                padding: 2px 4px;
            }
        """)

        # Protocol Filter Buttons
        self.proto_group = QButtonGroup(self)
        self.proto_group.setExclusive(True)

        self.all_filter_btn = QPushButton("All")
        self.sftp_filter_btn = QPushButton("SFTP")
        self.ssh_filter_btn = QPushButton("SSH")
        self.ftps_filter_btn = QPushButton("FTPS")

        for btn in (self.all_filter_btn, self.sftp_filter_btn, self.ssh_filter_btn, self.ftps_filter_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 5px;
                    color: #a1a1aa;
                    font-size: 11px;
                    padding: 0 8px;
                }
                QPushButton:hover {
                    color: #f4f4f5;
                    background: #222328;
                }
                QPushButton:checked {
                    background: rgba(99, 102, 241, 0.15);
                    border-color: rgba(99, 102, 241, 0.3);
                    color: #818cf8;
                    font-weight: 600;
                }
            """)
            self.proto_group.addButton(btn)

        self.all_filter_btn.setChecked(True)

        # View mode toggle (Grid vs Table)
        self.grid_mode_btn = QPushButton("Grid")
        self.grid_mode_btn.setCheckable(True)
        self.grid_mode_btn.setChecked(True)
        self.table_mode_btn = QPushButton("Table")
        self.table_mode_btn.setCheckable(True)

        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self.grid_mode_btn)
        view_group.addButton(self.table_mode_btn)

        for btn in (self.grid_mode_btn, self.table_mode_btn):
            btn.setFixedHeight(24)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 4px;
                    color: #71717a;
                    font-size: 11px;
                    padding: 0 6px;
                }
                QPushButton:checked {
                    background: #27272a;
                    color: #f4f4f5;
                    font-weight: 600;
                }
            """)

        filter_layout.addWidget(search_icon)
        filter_layout.addWidget(self.search_input, 1)
        filter_layout.addWidget(self.all_filter_btn)
        filter_layout.addWidget(self.sftp_filter_btn)
        filter_layout.addWidget(self.ssh_filter_btn)
        filter_layout.addWidget(self.ftps_filter_btn)
        filter_layout.addSpacing(6)
        filter_layout.addWidget(self.grid_mode_btn)
        filter_layout.addWidget(self.table_mode_btn)

        # 3. Stacked View Container (Grid vs Table vs Empty State)
        self.view_stack = QStackedWidget()

        # View 1: Card Grid Scroll Area
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet("QScrollArea { border: 0; background: transparent; }")

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 4, 0, 4)
        self.grid_layout.setHorizontalSpacing(12)
        self.grid_layout.setVerticalSpacing(12)
        self.grid_scroll.setWidget(self.grid_container)

        # View 2: Traditional Table Widget (Updated Theme)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Protocol", "Host", "Port", "User", "Auth", "Secret"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)

        # View 3: Empty State
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(20, 40, 20, 40)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon = QLabel()
        empty_icon.setPixmap(get_icon("servers", color="#3f3f46", size=48).pixmap(48, 48))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("No Saved Connections")
        empty_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #a1a1aa; margin-top: 10px;")
        empty_desc = QLabel("Click '+ New Connection' or press Ctrl+N to add your first server.")
        empty_desc.setStyleSheet("font-size: 12px; color: #71717a;")
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(empty_title, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_desc, alignment=Qt.AlignmentFlag.AlignCenter)

        self.view_stack.addWidget(self.grid_scroll)
        self.view_stack.addWidget(self.table)
        self.view_stack.addWidget(self.empty_state)

        # Legacy Action Buttons (Preserved for slot compat)
        self.connect_button = QPushButton("Connect")
        self.edit_button = QPushButton("Edit")
        self.rename_button = QPushButton("Rename")
        self.delete_button = QPushButton("Delete")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addLayout(header_box)
        layout.addWidget(filter_bar)
        layout.addWidget(self.view_stack, 1)

        # Connections
        self.search_input.textChanged.connect(self._on_search_changed)
        self.all_filter_btn.clicked.connect(lambda: self._set_protocol_filter("ALL"))
        self.sftp_filter_btn.clicked.connect(lambda: self._set_protocol_filter("SFTP"))
        self.ssh_filter_btn.clicked.connect(lambda: self._set_protocol_filter("SSH"))
        self.ftps_filter_btn.clicked.connect(lambda: self._set_protocol_filter("FTPS"))
        self.grid_mode_btn.clicked.connect(lambda: self._set_view_mode("grid"))
        self.table_mode_btn.clicked.connect(lambda: self._set_view_mode("table"))
        self.new_btn.clicked.connect(self.new_connection_requested.emit)
        self.connect_button.clicked.connect(self._connect_selected)
        self.edit_button.clicked.connect(self._edit_selected)
        self.rename_button.clicked.connect(self._rename_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.table.itemDoubleClicked.connect(lambda _item: self._connect_selected())

    def set_profiles(self, profiles: list[ConnectionProfile]) -> None:
        self._profiles = profiles
        self._render_views()

    def _render_views(self) -> None:
        filtered = self._get_filtered_profiles()

        if not filtered:
            if not self._profiles:
                self.view_stack.setCurrentWidget(self.empty_state)
            else:
                self.view_stack.setCurrentWidget(self.empty_state)
            return

        # 1. Render Grid
        # Clear existing cards
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        columns = 2
        for idx, profile in enumerate(filtered):
            card = ServerCardWidget(profile)
            card.connect_requested.connect(self.connect_requested.emit)
            card.edit_requested.connect(self.edit_requested.emit)
            card.delete_requested.connect(self.delete_requested.emit)
            card.rename_requested.connect(self.rename_requested.emit)
            row = idx // columns
            col = idx % columns
            self.grid_layout.addWidget(card, row, col)

        # Add vertical stretch to push cards up
        self.grid_layout.setRowStretch((len(filtered) // columns) + 1, 1)

        # 2. Render Table
        self.table.setRowCount(0)
        for profile in filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                profile.name,
                profile.protocol.value.upper(),
                profile.host,
                str(profile.port),
                profile.username,
                profile.auth_type.value,
                (
                    "OS keyring"
                    if profile.password_secret_ref
                    or profile.ssh_private_key_passphrase_secret_ref
                    else "Prompt"
                ),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(32, profile)
                self.table.setItem(row, column, item)

        self.table.resizeColumnsToContents()

        # Set active stack page
        if self._view_mode == "grid":
            self.view_stack.setCurrentWidget(self.grid_scroll)
        else:
            self.view_stack.setCurrentWidget(self.table)

    def _get_filtered_profiles(self) -> list[ConnectionProfile]:
        query = self._filter_text.strip().lower()
        res = []
        for p in self._profiles:
            # Check protocol
            if self._protocol_filter != "ALL" and p.protocol.value.upper() != self._protocol_filter:
                continue
            # Check search query
            if query:
                haystack = f"{p.name} {p.host} {p.username} {p.protocol.value}".lower()
                if query not in haystack:
                    continue
            res.append(p)
        return res

    def _on_search_changed(self, text: str) -> None:
        self._filter_text = text
        self._render_views()

    def _set_protocol_filter(self, proto: str) -> None:
        self._protocol_filter = proto
        self._render_views()

    def _set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        if self._profiles:
            self.view_stack.setCurrentWidget(self.grid_scroll if mode == "grid" else self.table)

    def selected_profile(self) -> ConnectionProfile | None:
        if self.view_stack.currentWidget() == self.table:
            rows = self.table.selectionModel().selectedRows()
            if not rows:
                return None
            item = self.table.item(rows[0].row(), 0)
            return item.data(32) if item else None
        # In grid mode, return the first profile if exists
        filtered = self._get_filtered_profiles()
        return filtered[0] if filtered else None

    def _connect_selected(self) -> None:
        profile = self.selected_profile()
        if profile:
            self.connect_requested.emit(profile)

    def _delete_selected(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        response = QMessageBox.question(self, "Delete saved profile", f"Delete saved profile {profile.name}?")
        if response == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(profile.id)

    def _edit_selected(self) -> None:
        profile = self.selected_profile()
        if profile is not None:
            self.edit_requested.emit(profile)

    def _rename_selected(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        name, ok = QInputDialog.getText(self, "Rename connection", "Connection name", text=profile.name)
        name = name.strip()
        if ok and name:
            self.rename_requested.emit(profile.id, name)
