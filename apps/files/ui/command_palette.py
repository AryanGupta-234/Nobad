from __future__ import annotations

from typing import Dict, List, Tuple
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ui.icons import get_icon
from ui.theme import DEFAULT_THEME, get_mono_font, get_ui_font


# Command specification: (id, title, shortcut, category, icon_name)
COMMAND_METADATA: List[Tuple[str, str, str, str, str]] = [
    ("Upload", "Upload Selected Files", "Alt+U", "Active Actions", "upload"),
    ("Download", "Download Selected Files", "Alt+D", "Active Actions", "download"),
    ("Open terminal here", "Open Terminal Here", "Ctrl+T", "Active Actions", "terminal"),
    ("Sync folder", "Trigger 2-Way Sync", "Alt+S", "Active Actions", "sync"),
    ("Connect", "Quick Connect to Server", "Ctrl+O", "Server", "connect"),
    ("Disconnect", "Disconnect Current Server", "", "Server", "disconnect"),
    ("New Host", "Configure New Host Profile", "", "Server", "servers"),
    ("Open dashboard", "Open Server Health & Resource Monitor", "Ctrl+Alt+H", "Navigation", "activity"),
    ("Open services", "Open Systemd Services Manager", "Ctrl+Alt+S", "Navigation", "services"),
    ("Open tunnels", "Open SSH Tunnels & Port Forwarding", "Ctrl+Alt+T", "Navigation", "tunnels"),
    ("Open log streamer", "Open Live Multi-Log Streamer", "Ctrl+Alt+L", "Navigation", "logs"),
    ("Open playbooks", "Open Script Snippets & 1-Click Playbooks", "Ctrl+Alt+P", "Navigation", "playbooks"),
    ("Open terminal", "Open Terminal (Default)", "", "Navigation", "terminal"),
    ("Open credentials", "Open Credential Vault", "", "Navigation", "credentials"),
    ("Open logs", "Open Activity & Diagnostic Logs", "", "Navigation", "activity"),
    ("Open settings", "Open Application Settings", "", "Navigation", "settings"),
    ("Edit file", "Open Selected File in Editor", "", "Files", "editor"),
    ("New file", "Create New File", "", "Files", "editor"),
    ("New folder", "Create New Directory", "", "Files", "folder"),
    ("Rename", "Rename Selected File", "", "Files", "editor"),
    ("Delete", "Delete Selected Files", "Del", "Files", "cancel"),
    ("Compress", "Compress Selected Files (Archive)", "", "Files", "archive"),
    ("Extract", "Extract Archive Here", "", "Files", "archive"),
    ("Calculate folder size", "Calculate Directory Disk Size", "", "Files", "search"),
    ("Copy path", "Copy Full Path to Clipboard", "", "Files", "copy"),
    ("Clear queue", "Clear Completed Transfers", "", "Transfers", "cancel"),
    ("Retry failed transfers", "Retry All Failed Transfers", "", "Transfers", "sync"),
]


class CommandItemDelegate(QStyledItemDelegate):
    """Raycast-style list item with category, icon, title, and shortcut badge."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._title_font = get_ui_font(size=11, weight=QFont.Weight.Medium)
        self._kbd_font = get_mono_font(size=10, weight=QFont.Weight.Medium)
        self._cat_font = get_ui_font(size=9, weight=QFont.Weight.Bold)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        is_selected = bool(option.state & option.state.State_Selected)

        # Background
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(DEFAULT_THEME.surface_hover))
            painter.drawRoundedRect(rect.adjusted(4, 2, -4, -2), 6, 6)
            # Accent left border indicator
            accent_rect = QRect(rect.left() + 4, rect.top() + 6, 3, rect.height() - 12)
            painter.fillRect(accent_rect, QColor(DEFAULT_THEME.accent))

        # Retrieve metadata
        title = index.data(Qt.ItemDataRole.UserRole + 1) or index.data(Qt.ItemDataRole.DisplayRole) or ""
        shortcut = index.data(Qt.ItemDataRole.UserRole + 2) or ""
        category = index.data(Qt.ItemDataRole.UserRole + 3) or ""
        icon = index.data(Qt.ItemDataRole.DecorationRole)

        # Draw icon
        icon_x = rect.left() + 16
        icon_y = rect.top() + (rect.height() - 18) // 2
        if isinstance(icon, QColor) or icon:
            icon_rect = QRect(icon_x, icon_y, 18, 18)
            if hasattr(icon, "paint"):
                icon.paint(painter, icon_rect)

        # Draw Title
        painter.setFont(self._title_font)
        painter.setPen(QColor(DEFAULT_THEME.text if is_selected else DEFAULT_THEME.text_muted))
        title_rect = QRect(rect.left() + 44, rect.top(), rect.width() - 160, rect.height())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(title))

        # Draw Shortcut badge
        if shortcut:
            painter.setFont(self._kbd_font)
            badge_width = len(shortcut) * 7 + 14
            badge_height = 20
            badge_x = rect.right() - badge_width - 12
            badge_y = rect.top() + (rect.height() - badge_height) // 2
            badge_rect = QRect(badge_x, badge_y, badge_width, badge_height)

            # Badge background
            painter.setPen(QPen(QColor(DEFAULT_THEME.border), 1))
            painter.setBrush(QColor(DEFAULT_THEME.surface))
            painter.drawRoundedRect(badge_rect, 4, 4)

            # Badge text
            painter.setPen(QColor(DEFAULT_THEME.text_dim))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, shortcut)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), 36)


class CommandPalette(QDialog):
    command_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(560)
        self.setFixedHeight(380)

        # Card container with shadow
        self.card = QFrame(self)
        self.card.setObjectName("CommandPaletteCard")
        self.card.setStyleSheet(
            f"""
            QFrame#CommandPaletteCard {{
                background-color: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 12px;
            }}
            """
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 8)
        self.card.setGraphicsEffect(shadow)

        # Header Search Input
        search_row = QHBoxLayout()
        search_row.setContentsMargins(14, 12, 14, 12)
        search_row.setSpacing(10)

        search_icon = QLabel()
        search_icon.setPixmap(get_icon("search", color=DEFAULT_THEME.text_muted, size=16).pixmap(16, 16))
        search_row.addWidget(search_icon)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command or search actions...")
        self.search.setStyleSheet(
            f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {DEFAULT_THEME.text};
                font-size: 14px;
                padding: 0;
            }}
            """
        )
        search_row.addWidget(self.search, 1)

        esc_badge = QLabel("ESC")
        esc_badge.setStyleSheet(
            f"""
            QLabel {{
                background: {DEFAULT_THEME.surface};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 4px;
                color: {DEFAULT_THEME.text_dim};
                font-family: 'JetBrains Mono', monospace;
                font-size: 10px;
                padding: 2px 6px;
            }}
            """
        )
        search_row.addWidget(esc_badge)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {DEFAULT_THEME.border}; max-height: 1px;")

        # Results List
        self.list = QListWidget()
        self.list.setStyleSheet("background: transparent; border: none; padding: 4px;")
        self.list.setItemDelegate(CommandItemDelegate(self.list))
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Bottom Hints Bar
        footer = QFrame()
        footer.setObjectName("CommandPaletteFooter")
        footer.setStyleSheet(
            f"""
            QFrame#CommandPaletteFooter {{
                background-color: {DEFAULT_THEME.surface};
                border-top: 1px solid {DEFAULT_THEME.border};
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
            """
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 6, 14, 6)
        hint_label = QLabel("↑↓ Navigate  •  ↵ Select  •  ESC Close")
        hint_label.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; font-size: 11px;")
        mode_label = QLabel("Raycast Spotlight")
        mode_label.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; font-size: 11px;")
        footer_layout.addWidget(hint_label)
        footer_layout.addStretch()
        footer_layout.addWidget(mode_label)

        # Card Layout
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addLayout(search_row)
        card_layout.addWidget(sep)
        card_layout.addWidget(self.list, 1)
        card_layout.addWidget(footer)

        # Dialog Layout
        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(16, 16, 16, 16)
        dialog_layout.addWidget(self.card)

        # Populate initial commands
        self._populate(COMMAND_METADATA)

        # Event connections
        self.search.textChanged.connect(self._filter)
        self.list.itemActivated.connect(self._on_item_activated)

    def _populate(self, commands: List[Tuple[str, str, str, str, str]]) -> None:
        self.list.clear()
        for cmd_id, title, shortcut, category, icon_name in commands:
            item = QListWidgetItem(self.list)
            item.setData(Qt.ItemDataRole.UserRole, cmd_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, title)
            item.setData(Qt.ItemDataRole.UserRole + 2, shortcut)
            item.setData(Qt.ItemDataRole.UserRole + 3, category)
            item.setData(Qt.ItemDataRole.DecorationRole, get_icon(icon_name, size=18))
            self.list.addItem(item)
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        if not q:
            self._populate(COMMAND_METADATA)
            return

        filtered = [
            cmd for cmd in COMMAND_METADATA
            if q in cmd[0].lower() or q in cmd[1].lower() or q in cmd[3].lower()
        ]
        self._populate(filtered)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        cmd_id = item.data(Qt.ItemDataRole.UserRole)
        if cmd_id:
            self.command_selected.emit(cmd_id)
            self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Down:
            row = (self.list.currentRow() + 1) % max(1, self.list.count())
            self.list.setCurrentRow(row)
            event.accept()
        elif event.key() == Qt.Key.Key_Up:
            row = (self.list.currentRow() - 1 + self.list.count()) % max(1, self.list.count())
            self.list.setCurrentRow(row)
            event.accept()
        elif event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            curr = self.list.currentItem()
            if curr is not None:
                self._on_item_activated(curr)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
        else:
            super().keyPressEvent(event)
