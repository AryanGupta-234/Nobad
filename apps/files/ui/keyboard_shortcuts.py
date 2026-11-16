from __future__ import annotations

"""Scoped, discoverable keyboard access for ordinary Qt buttons."""

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QPushButton, QWidget


def install_button_shortcuts(root: QWidget) -> list[QShortcut]:
    """Give every currently-created button an Alt shortcut within its own panel.

    Keeping the shortcuts scoped to a button's parent avoids collisions between
    matching controls in the local and remote file panes. The tooltip is the
    visible reference for the assigned key.
    """

    shortcuts: list[QShortcut] = []
    used_keys: dict[QWidget, set[str]] = defaultdict(set)
    for button in root.findChildren(QPushButton):
        label = button.text().replace("&", "").strip()
        scope = button.parentWidget()
        if not label or scope is None:
            continue
        key = _available_key(label, used_keys[scope])
        if key is None:
            continue
        used_keys[scope].add(key)
        sequence = QKeySequence(f"Alt+{key.upper()}")
        shortcut = QShortcut(sequence, scope)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda button=button: button.click() if button.isVisible() and button.isEnabled() else None)
        tooltip = button.toolTip().strip()
        suffix = f"Shortcut: {sequence.toString(QKeySequence.SequenceFormat.NativeText)}"
        button.setToolTip(f"{tooltip}\n{suffix}" if tooltip else suffix)
        shortcuts.append(shortcut)
    return shortcuts


def _available_key(label: str, used: set[str]) -> str | None:
    for character in label:
        key = character.lower()
        if key.isalnum() and key not in used:
            return key
    return None
