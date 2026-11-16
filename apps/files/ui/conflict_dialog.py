from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from ui.icons import get_icon
from ui.theme import DEFAULT_THEME


class ConflictDialog(QDialog):
    """Modern conflict resolution dialog for file transfers."""

    def __init__(self, parent=None, filename: str = "", local_info: str = "", remote_info: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Transfer Conflict")
        self.setFixedWidth(460)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        # Header with warning badge
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        warn_icon = QLabel()
        warn_icon.setPixmap(get_icon("sync", color=DEFAULT_THEME.warning, size=24).pixmap(24, 24))
        header_row.addWidget(warn_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel("File Conflict Detected")
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(f"Destination already contains: {filename}" if filename else "Target item already exists.")
        subtitle_label.setObjectName("MutedLabel")
        subtitle_label.setWordWrap(True)
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)
        header_row.addLayout(title_box, 1)
        main_layout.addLayout(header_row)

        # Card container for choices
        card = QFrame()
        card.setObjectName("StatusBadge")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)

        policy_row = QHBoxLayout()
        policy_label = QLabel("Resolution Policy:")
        policy_label.setObjectName("MutedLabel")
        self.policy = QComboBox()
        self.policy.addItems([
            ConflictPolicy.OVERWRITE.value,
            ConflictPolicy.SKIP.value,
            ConflictPolicy.RENAME.value,
        ])
        self.policy.setMinimumWidth(160)
        policy_row.addWidget(policy_label)
        policy_row.addWidget(self.policy, 1)
        card_layout.addLayout(policy_row)

        self.apply_to_all = QCheckBox("Apply to all remaining conflicts in this transfer")
        self.apply_to_all.setChecked(True)
        card_layout.addWidget(self.apply_to_all)

        main_layout.addWidget(card)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.cancel_button = QPushButton("Cancel Transfer")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton("Apply Decision")
        self.ok_button.setObjectName("PrimaryButton")
        self.ok_button.clicked.connect(self.accept)

        btn_row.addStretch()
        btn_row.addWidget(self.cancel_button)
        btn_row.addWidget(self.ok_button)
        main_layout.addLayout(btn_row)

    def selected_policy(self) -> ConflictPolicy:
        return ConflictPolicy(self.policy.currentText())

    def selected_decision(self) -> ConflictDecision:
        return ConflictDecision(self.selected_policy(), apply_to_all=self.apply_to_all.isChecked())
