from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout

from transfers.remote_transfer import RemoteTransferMode


class RemoteTransferDialog(QDialog):
    def __init__(self, profiles: list, *, default_path: str = ".", parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("Copy to server")
        self.profiles = profiles
        self.profile = QComboBox()
        for saved_profile in profiles:
            self.profile.addItem(
                f"{saved_profile.name} ({saved_profile.protocol.value.upper()})",
                saved_profile,
            )
        self.destination_path = QLineEdit(default_path)
        self.mode = QComboBox()
        self.mode.addItem("Auto", RemoteTransferMode.AUTO)
        self.mode.addItem("Secure local relay", RemoteTransferMode.LOCAL_RELAY)
        self.mode.addItem("Rsync push", RemoteTransferMode.RSYNC_PUSH)
        self.mode.addItem("Rsync pull", RemoteTransferMode.RSYNC_PULL)
        form = QFormLayout()
        form.addRow("Destination server", self.profile)
        form.addRow("Destination folder", self.destination_path)
        form.addRow("Transfer mode", self.mode)
        cancel = QPushButton("Cancel")
        copy = QPushButton("Preview")
        copy.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        copy.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(copy)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(actions)

    def values(self) -> tuple[object | None, str, RemoteTransferMode]:
        return (
            self.profile.currentData(),
            self.destination_path.text().strip() or ".",
            self.mode.currentData(),
        )
