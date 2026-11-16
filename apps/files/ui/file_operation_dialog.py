from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout


class FileOperationDialog(QDialog):
    def __init__(self, message: str, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("File Operation")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(message))

