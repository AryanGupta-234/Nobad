from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class Sidebar(QListWidget):
    section_selected = Signal(str)

    SECTIONS = [
        "Connections",
        "File Manager",
        "Activity",
        "Terminal",
        "Sync Jobs",
        "Editor",
        "Deployments",
        "Settings",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(180)
        for section in self.SECTIONS:
            QListWidgetItem(section, self)
        self.setCurrentRow(1)
        self.currentTextChanged.connect(self.section_selected.emit)
