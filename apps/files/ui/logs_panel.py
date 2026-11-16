from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget


class LogsPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.clear_button = QPushButton("Clear")
        self.copy_button = QPushButton("Copy")

        controls = QHBoxLayout()
        controls.addWidget(self.clear_button)
        controls.addWidget(self.copy_button)
        controls.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.output)

        self.clear_button.clicked.connect(self.output.clear)
        self.copy_button.clicked.connect(self.output.copy)

    def append_log(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output.append(f"[{timestamp}] {level.upper()}: {message}")

