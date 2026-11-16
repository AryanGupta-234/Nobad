from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from core.playbooks_manager import choose_sudo_password


class SudoPasswordDialog(QDialog):
    """Asks for the sudo password of one playbook run. Reusing the SSH login password is opt-in (#32)."""

    def __init__(self, host: str, *, login_password_available: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sudo password")
        intro = QLabel(
            f"This playbook runs commands with sudo on {host}. Enter the sudo password, or run it without one "
            "(sudo will then wait for a password and you can cancel)."
        )
        intro.setWordWrap(True)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Sudo password")
        self.reuse_login = QCheckBox("Use my SSH login password for sudo")
        self.reuse_login.setChecked(False)
        self.reuse_login.setEnabled(login_password_available)
        if not login_password_available:
            self.reuse_login.setToolTip("This connection didn't use a saved password.")
        self.reuse_login.toggled.connect(lambda on: self.password_input.setEnabled(not on))
        note = QLabel("The password is only sent when sudo itself asks for it, once, and is never saved.")
        note.setWordWrap(True)
        note.setObjectName("MutedLabel")

        buttons = QDialogButtonBox()
        self.run_button = buttons.addButton("Run", QDialogButtonBox.ButtonRole.AcceptRole)
        self.run_without_button = buttons.addButton("Run without sudo password", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.run_without_button.clicked.connect(self._run_without)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._without = False

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.password_input)
        layout.addWidget(self.reuse_login)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _run_without(self) -> None:
        self._without = True

    def sudo_password(self, login_password: str | None) -> str | None:
        if self._without:
            return None
        return choose_sudo_password(
            typed_password=self.password_input.text(),
            reuse_login_password=self.reuse_login.isChecked(),
            login_password=login_password,
        )
