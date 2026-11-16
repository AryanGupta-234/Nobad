from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from sync.conflicts import SyncConflictChoice, SyncConflictDecision
from sync.diff_engine import SyncPlanEntry


class SyncConflictDialog(QDialog):
    def __init__(
        self,
        conflicts: list[SyncPlanEntry],
        *,
        compare_callback: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resolve sync conflicts")
        self.resize(850, 460)
        self._conflicts = conflicts
        self._compare_callback = compare_callback
        self.table = QTableWidget(len(conflicts), 3)
        self.table.setHorizontalHeaderLabels(["Path", "Reason", "Resolution"])
        for row, entry in enumerate(conflicts):
            self.table.setItem(row, 0, QTableWidgetItem(entry.path))
            self.table.setItem(row, 1, QTableWidgetItem(entry.reason))
            combo = QComboBox()
            combo.addItem("Choose...", None)
            combo.addItem("Use Local", SyncConflictChoice.USE_LOCAL)
            combo.addItem("Use Remote", SyncConflictChoice.USE_REMOTE)
            combo.addItem("Keep Both", SyncConflictChoice.KEEP_BOTH)
            combo.addItem("Skip", SyncConflictChoice.SKIP)
            self.table.setCellWidget(row, 2, combo)
        self.table.resizeColumnsToContents()
        compare = QPushButton("Compare Selected")
        apply_button = QPushButton("Apply Resolutions")
        apply_button.setObjectName("PrimaryButton")
        cancel = QPushButton("Cancel")
        compare.setEnabled(compare_callback is not None)
        compare.clicked.connect(self._compare_selected)
        apply_button.clicked.connect(self._accept_if_complete)
        cancel.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(compare)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(apply_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)

    def decisions(self) -> list[SyncConflictDecision]:
        decisions: list[SyncConflictDecision] = []
        for row, entry in enumerate(self._conflicts):
            combo = self.table.cellWidget(row, 2)
            choice = combo.currentData(Qt.ItemDataRole.UserRole) if isinstance(combo, QComboBox) else None
            if choice is None:
                continue
            decisions.append(SyncConflictDecision(entry.path, choice))
        return decisions

    def _accept_if_complete(self) -> None:
        if len(self.decisions()) != len(self._conflicts):
            QMessageBox.warning(self, "Unresolved conflicts", "Choose a resolution for every conflict.")
            return
        self.accept()

    def _compare_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Compare conflict", "Select a conflict row first.")
            return
        if self._compare_callback:
            self._compare_callback(self._conflicts[row].path)
