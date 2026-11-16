from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from editor.diff_engine import DiffHunk, TextDiffEngine
from ui.code_editor import CodeEditorWidget
from ui.icons import get_icon


class DiffViewer(QWidget):
    def __init__(
        self,
        left_text: str,
        right_text: str,
        *,
        left_label: str = "Local",
        right_label: str = "Remote",
    ) -> None:
        super().__init__()
        self.hunks = [hunk for hunk in TextDiffEngine().compare(left_text, right_text) if hunk.changed]
        self._hunk_index = -1
        self.left = CodeEditorWidget(text=left_text, readonly=True)
        self.right = CodeEditorWidget(text=right_text, readonly=True)
        self._sync_scrollbars()
        self.status = QLabel(self._status_text())
        self.status.setObjectName("MutedLabel")
        previous = QPushButton("Previous")
        previous.setIcon(get_icon("upload", size=14))
        next_button = QPushButton("Next")
        next_button.setIcon(get_icon("download", size=14))
        previous.clicked.connect(self.previous_change)
        next_button.clicked.connect(self.next_change)

        left_title = QLabel(f"● {left_label}")
        left_title.setStyleSheet("color: #818cf8; font-weight: 600; font-size: 12px;")
        left_box = QVBoxLayout()
        left_box.addWidget(left_title)
        left_box.addWidget(self.left)

        right_title = QLabel(f"● {right_label}")
        right_title.setStyleSheet("color: #10b981; font-weight: 600; font-size: 12px;")
        right_box = QVBoxLayout()
        right_box.addWidget(right_title)
        right_box.addWidget(self.right)

        panes = QHBoxLayout()
        panes.addLayout(left_box, 1)
        panes.addLayout(right_box, 1)

        toolbar = QHBoxLayout()
        toolbar.addWidget(previous)
        toolbar.addWidget(next_button)
        toolbar.addWidget(self.status)
        toolbar.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addLayout(panes, 1)
        if self.hunks:
            self.next_change()

    def next_change(self) -> DiffHunk | None:
        if not self.hunks:
            return None
        self._hunk_index = (self._hunk_index + 1) % len(self.hunks)
        return self._show_current()

    def previous_change(self) -> DiffHunk | None:
        if not self.hunks:
            return None
        self._hunk_index = (self._hunk_index - 1) % len(self.hunks)
        return self._show_current()

    def _show_current(self) -> DiffHunk:
        hunk = self.hunks[self._hunk_index]
        self.left.goto_line(hunk.left_start)
        self.right.goto_line(hunk.right_start)
        self.left.highlight_lines(hunk.left_start, hunk.left_end)
        self.right.highlight_lines(hunk.right_start, hunk.right_end)
        self.status.setText(self._status_text())
        return hunk

    def _status_text(self) -> str:
        if not self.hunks:
            return "No differences"
        current = self._hunk_index + 1 if self._hunk_index >= 0 else 0
        return f"Change {current}/{len(self.hunks)}"

    def _sync_scrollbars(self) -> None:
        left_scroll = self.left.editor.verticalScrollBar()
        right_scroll = self.right.editor.verticalScrollBar()
        left_scroll.valueChanged.connect(
            lambda value: right_scroll.setValue(value) if right_scroll.value() != value else None
        )
        right_scroll.valueChanged.connect(
            lambda value: left_scroll.setValue(value) if left_scroll.value() != value else None
        )


class DiffViewerDialog(QDialog):
    def __init__(self, left_text: str, right_text: str, *, title: str = "Compare files", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 720)
        layout = QVBoxLayout(self)
        layout.addWidget(DiffViewer(left_text, right_text), 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
