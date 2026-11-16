from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ui.theme import DEFAULT_THEME, get_mono_font, get_ui_font


class FileTableItemDelegate(QStyledItemDelegate):
    """Custom item delegate for sleek Linear/Raycast file table rendering."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mono_font = get_mono_font(size=11)
        self._ui_font = get_ui_font(size=11)
        self._pill_font = get_mono_font(size=10, weight=QFont.Weight.Medium)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        column = index.column()
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # Background row rendering
        rect = option.rect
        if is_selected:
            # Subtle indigo tint
            painter.fillRect(rect, QColor(99, 102, 241, 35))
            # Left accent bar on first column
            if column == 0:
                accent_bar = QRect(rect.left(), rect.top() + 2, 3, rect.height() - 4)
                painter.fillRect(accent_bar, QColor(DEFAULT_THEME.accent))
        elif is_hover:
            painter.fillRect(rect, QColor(DEFAULT_THEME.surface_hover))

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        # Column 0: Name (UI Font, bold if directory)
        if column == 0:
            super().paint(painter, option, index)
            painter.restore()
            return

        # Column 1: Size (Tabular Monospace, Right-Aligned)
        if column == 1:
            painter.setFont(self._mono_font)
            text_color = QColor(DEFAULT_THEME.text if is_selected else DEFAULT_THEME.text_muted)
            painter.setPen(text_color)
            padding_rect = rect.adjusted(4, 0, -12, 0)
            painter.drawText(padding_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(text))
            painter.restore()
            return

        # Column 4: Permissions (Sleek Monospace Pill Chip)
        if column == 4 and text:
            painter.setFont(self._pill_font)
            # Pill background
            pill_width = min(80, max(54, len(str(text)) * 7 + 14))
            pill_height = 20
            pill_x = rect.left() + 8
            pill_y = rect.top() + (rect.height() - pill_height) // 2
            pill_rect = QRect(pill_x, pill_y, pill_width, pill_height)

            # Soft background
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(DEFAULT_THEME.surface_card))
            painter.drawRoundedRect(pill_rect, 4, 4)

            # Border
            painter.setPen(QPen(QColor(DEFAULT_THEME.border), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(pill_rect, 4, 4)

            # Text
            painter.setPen(QColor(DEFAULT_THEME.text_muted))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, str(text))
            painter.restore()
            return

        # Column 3: Modified (Monospace Muted)
        if column == 3:
            painter.setFont(self._mono_font)
            painter.setPen(QColor(DEFAULT_THEME.text_dim))
            padding_rect = rect.adjusted(8, 0, -8, 0)
            painter.drawText(padding_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(text))
            painter.restore()
            return

        # Default Column Fallback
        painter.setFont(self._ui_font)
        painter.setPen(QColor(DEFAULT_THEME.text_muted))
        padding_rect = rect.adjusted(8, 0, -8, 0)
        painter.drawText(padding_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(text))
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        hint = super().sizeHint(option, index)
        # Ensure minimum 32px height for comfortable touch/mouse target
        hint.setHeight(max(32, hint.height()))
        return hint
