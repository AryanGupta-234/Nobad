from __future__ import annotations

import math
import secrets
import string
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from credentials.import_export import CredentialImportExportService
from credentials.models import (
    CREDENTIAL_KIND_LABELS,
    CredentialItem,
    CredentialKind,
    CredentialProject,
    format_tags,
    parse_tags,
)
from credentials.vault_service import CredentialVaultService
from ui.icons import get_icon


USER_ROLE = int(Qt.ItemDataRole.UserRole)


def _calculate_entropy(password: str) -> float:
    if not password:
        return 0.0
    pool = 0
    if any(c.islower() for c in password):
        pool += 26
    if any(c.isupper() for c in password):
        pool += 26
    if any(c.isdigit() for c in password):
        pool += 10
    if any(c in string.punctuation for c in password):
        pool += 32
    if pool == 0:
        return 0.0
    return round(len(password) * math.log2(pool), 1)


def _generate_secure_password(length: int = 24, use_symbols: bool = True, use_numbers: bool = True, use_upper: bool = True) -> str:
    alphabet = string.ascii_lowercase
    guaranteed = [secrets.choice(string.ascii_lowercase)]
    if use_upper:
        alphabet += string.ascii_uppercase
        guaranteed.append(secrets.choice(string.ascii_uppercase))
    if use_numbers:
        alphabet += string.digits
        guaranteed.append(secrets.choice(string.digits))
    if use_symbols:
        symbols = "!@#$%^&*()-_=+[]{}<>?"
        alphabet += symbols
        guaranteed.append(secrets.choice(symbols))

    remaining = [secrets.choice(alphabet) for _ in range(max(0, length - len(guaranteed)))]
    result_chars = guaranteed + remaining
    # Shuffle using Fisher-Yates with secrets
    for i in range(len(result_chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        result_chars[i], result_chars[j] = result_chars[j], result_chars[i]
    return "".join(result_chars)


class MasterPasswordDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Master Password")
        self.setFixedWidth(380)

        title = QLabel("Change Master Password")
        title.setObjectName("SectionTitle")
        body = QLabel("Update the master passphrase used to encrypt your vault.")
        body.setObjectName("MutedLabel")
        body.setWordWrap(True)

        self.current = QLineEdit()
        self.current.setEchoMode(QLineEdit.EchoMode.Password)
        self.current.setPlaceholderText("Current master password")

        self.new = QLineEdit()
        self.new.setEchoMode(QLineEdit.EchoMode.Password)
        self.new.setPlaceholderText("New master password")

        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.setPlaceholderText("Confirm new master password")

        self.save_button = QPushButton("Update Password")
        self.save_button.setObjectName("PrimaryButton")
        cancel = QPushButton("Cancel")

        form = QFormLayout()
        form.setContentsMargins(0, 10, 0, 10)
        form.addRow("Current", self.current)
        form.addRow("New", self.new)
        form.addRow("Confirm", self.confirm)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addLayout(form)
        layout.addLayout(buttons)

        cancel.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._accept_if_valid)

    def values(self) -> tuple[str, str]:
        return self.current.text(), self.new.text()

    def _accept_if_valid(self) -> None:
        if self.new.text() != self.confirm.text():
            QMessageBox.warning(self, "Password mismatch", "New password and confirmation do not match.")
            return
        if len(self.new.text()) < 6:
            QMessageBox.warning(self, "Password too short", "Master password must be at least 6 characters.")
            return
        self.accept()


class BulkImportDialog(QDialog):
    def __init__(
        self,
        import_export: CredentialImportExportService,
        project: CredentialProject,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bulk Import Credentials")
        self.setMinimumSize(920, 620)
        self.import_export = import_export
        self.project = project
        self.result = None
        self._items: list[dict] = []

        title = QLabel(f"Bulk Import into '{project.name}'")
        title.setObjectName("PageTitle")
        hint = QLabel("Paste credential notes, .env snippets, or credentials documentation. Secrets stay masked in preview.")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)

        self.text_input = QTextEdit()
        self.text_input.setAcceptRichText(False)
        self.text_input.setStyleSheet("QTextEdit { background: #0c0d10; color: #f4f4f5; font-family: monospace; border: 1px solid #27272a; border-radius: 6px; }")
        self.text_input.setPlaceholderText(
            "Example:\n"
            "Server Credentials\n"
            "URL : ssh -p 65002 user@example.com\n"
            "Password : ...\n\n"
            "GOOGLE_API_KEY=AIzaSy...\n"
            "DATABASE_URL=postgresql://user:pass@localhost:5432/db"
        )

        self.preview_table = QTableWidget(0, 5)
        self.preview_table.setHorizontalHeaderLabels(["Title", "Kind", "User / Key", "Host / URL", "Secret"])
        self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setShowGrid(False)
        self.preview_table.setStyleSheet("QTableWidget { background: #121215; border: 1px solid #27272a; border-radius: 6px; }")

        self.status = QLabel("Paste text above, then click Preview.")
        self.status.setObjectName("MutedLabel")

        self.conflict_policy = QComboBox()
        self.conflict_policy.addItem("Rename duplicates", "rename")
        self.conflict_policy.addItem("Overwrite duplicates", "overwrite")
        self.conflict_policy.addItem("Skip duplicates", "skip")

        self.preview_button = QPushButton("Preview Detection")
        self.preview_button.setIcon(get_icon("search", size=14))
        self.import_button = QPushButton("Import Now")
        self.import_button.setIcon(get_icon("check", size=14))
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setEnabled(False)
        cancel = QPushButton("Cancel")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Handling:"))
        controls.addWidget(self.conflict_policy)
        controls.addStretch()
        controls.addWidget(self.preview_button)
        controls.addWidget(cancel)
        controls.addWidget(self.import_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.text_input, 2)
        layout.addWidget(self.status)
        layout.addWidget(self.preview_table, 3)
        layout.addLayout(controls)

        self.preview_button.clicked.connect(self._preview)
        self.import_button.clicked.connect(self._import)
        cancel.clicked.connect(self.reject)

    def _preview(self) -> None:
        text = self.text_input.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "Bulk import", "Paste credential text first.")
            return
        result = self.import_export.preview_loose_text_import(self.project.id, text)
        if not result.ok:
            QMessageBox.warning(self, "Bulk import", result.message)
            return
        self._items = list(result.data["items"])
        preview = result.data["preview"]
        self.preview_table.setRowCount(0)
        for payload in self._items:
            row = self.preview_table.rowCount()
            self.preview_table.insertRow(row)
            values = [
                str(payload.get("title") or "Imported Credential"),
                self._kind_label(str(payload.get("kind") or "")),
                str(payload.get("environment_key") or payload.get("username") or ""),
                str(payload.get("url_host") or ""),
                "••••••••" if str(payload.get("secret_value") or "") else "",
            ]
            for column, value in enumerate(values):
                self.preview_table.setItem(row, column, QTableWidgetItem(value))
        self.preview_table.resizeColumnsToContents()
        self.status.setText(
            f"Detected {preview.entries} credentials. (New: {preview.creates}, Potential Conflicts: {preview.conflicts})"
        )
        self.import_button.setEnabled(bool(self._items))

    def _import(self) -> None:
        if not self._items:
            self._preview()
            if not self._items:
                return
        policy = str(self.conflict_policy.currentData() or "rename")
        self.result = self.import_export.import_loose_text(self.project.id, self.text_input.toPlainText(), conflict_policy=policy)
        if not self.result.ok:
            QMessageBox.warning(self, "Bulk import", self.result.message)
            return
        self.accept()

    def _kind_label(self, value: str) -> str:
        try:
            return CREDENTIAL_KIND_LABELS.get(CredentialKind(value), value)
        except ValueError:
            return value or CREDENTIAL_KIND_LABELS[CredentialKind.OTHER]


class RevealCredentialDialog(QDialog):
    def __init__(self, title: str, secret_value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Secret: {title}")
        self.setFixedWidth(460)
        self.secret_value = secret_value

        title_lbl = QLabel(f"Secret: {title}")
        title_lbl.setObjectName("SectionTitle")
        label = QLabel("Decrypted secret value (auto-clears clipboard in 30 seconds):")
        label.setObjectName("MutedLabel")
        label.setWordWrap(True)

        self.value = QTextEdit()
        self.value.setReadOnly(True)
        self.value.setAcceptRichText(False)
        self.value.setPlainText(secret_value)
        self.value.setStyleSheet("QTextEdit { background: #0c0d10; color: #10b981; font-family: monospace; font-size: 13px; border: 1px solid #27272a; border-radius: 6px; padding: 8px; }")
        self.value.setMaximumHeight(120)

        self.copy_button = QPushButton("Copy to Clipboard")
        self.copy_button.setIcon(get_icon("copy", size=14))
        ok = QPushButton("Close")
        ok.setObjectName("PrimaryButton")

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(title_lbl)
        layout.addWidget(label)
        layout.addWidget(self.value)
        layout.addLayout(buttons)

        self.copy_button.clicked.connect(self._copy)
        ok.clicked.connect(self.accept)

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.secret_value)
        self.copy_button.setText("Copied!")
        QTimer.singleShot(2000, lambda: self.copy_button.setText("Copy to Clipboard"))
        QTimer.singleShot(30000, lambda: clipboard.clear() if clipboard.text() == self.secret_value else None)


class PasswordGeneratorWidget(QFrame):
    password_generated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GeneratorFrame")
        self.setStyleSheet("""
            QFrame#GeneratorFrame {
                background: #141418;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header with Entropy Badge
        header_row = QHBoxLayout()
        gen_label = QLabel("PASSWORD GENERATOR")
        gen_label.setStyleSheet("font-size: 10px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px;")
        self.entropy_badge = QLabel("128 bits • Very Strong")
        self.entropy_badge.setStyleSheet("font-size: 10px; color: #10b981; font-weight: 600; background: rgba(16, 185, 129, 0.12); padding: 2px 6px; border-radius: 4px;")
        header_row.addWidget(gen_label)
        header_row.addStretch()
        header_row.addWidget(self.entropy_badge)
        layout.addLayout(header_row)

        # Slider row
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Length:"))
        self.length_slider = QSlider(Qt.Orientation.Horizontal)
        self.length_slider.setRange(8, 64)
        self.length_slider.setValue(24)
        self.length_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #27272a; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #6366f1; border-radius: 2px; }
            QSlider::handle:horizontal { width: 14px; height: 14px; margin-top: -5px; margin-bottom: -5px; border-radius: 7px; background: #f4f4f5; }
        """)
        self.length_label = QLabel("24 chars")
        self.length_label.setStyleSheet("color: #a1a1aa; font-family: monospace; font-size: 11px; min-width: 50px;")
        slider_row.addWidget(self.length_slider, 1)
        slider_row.addWidget(self.length_label)
        layout.addLayout(slider_row)

        # Options row
        opts_row = QHBoxLayout()
        self.opt_symbols = QCheckBox("Symbols (!@#)")
        self.opt_symbols.setChecked(True)
        self.opt_numbers = QCheckBox("Numbers (0-9)")
        self.opt_numbers.setChecked(True)
        self.opt_upper = QCheckBox("Uppercase (A-Z)")
        self.opt_upper.setChecked(True)
        opts_row.addWidget(self.opt_symbols)
        opts_row.addWidget(self.opt_numbers)
        opts_row.addWidget(self.opt_upper)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        # Preview output + Action Buttons
        preview_row = QHBoxLayout()
        self.preview_output = QLineEdit()
        self.preview_output.setReadOnly(True)
        self.preview_output.setStyleSheet("QLineEdit { background: #0c0d10; color: #f4f4f5; font-family: monospace; font-size: 12px; border: 1px solid #27272a; padding: 6px 8px; border-radius: 6px; }")

        self.btn_refresh = QPushButton()
        self.btn_refresh.setIcon(get_icon("refresh", size=14))
        self.btn_refresh.setToolTip("Generate New")
        self.btn_refresh.setFixedSize(32, 32)

        self.btn_use = QPushButton("Use Password")
        self.btn_use.setIcon(get_icon("check", size=14))
        self.btn_use.setStyleSheet("QPushButton { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.4); font-weight: 600; padding: 0 12px; height: 32px; border-radius: 6px; } QPushButton:hover { background: rgba(99, 102, 241, 0.35); }")

        preview_row.addWidget(self.preview_output, 1)
        preview_row.addWidget(self.btn_refresh)
        preview_row.addWidget(self.btn_use)
        layout.addLayout(preview_row)

        # Bindings
        self.length_slider.valueChanged.connect(self._on_slider_changed)
        self.opt_symbols.toggled.connect(lambda: self.generate())
        self.opt_numbers.toggled.connect(lambda: self.generate())
        self.opt_upper.toggled.connect(lambda: self.generate())
        self.btn_refresh.clicked.connect(lambda: self.generate())
        self.btn_use.clicked.connect(self._use_password)

        self.generate()

    def _on_slider_changed(self, value: int) -> None:
        self.length_label.setText(f"{value} chars")
        self.generate()

    def generate(self) -> str:
        length = self.length_slider.value()
        pwd = _generate_secure_password(
            length=length,
            use_symbols=self.opt_symbols.isChecked(),
            use_numbers=self.opt_numbers.isChecked(),
            use_upper=self.opt_upper.isChecked(),
        )
        self.preview_output.setText(pwd)
        entropy = _calculate_entropy(pwd)
        if entropy > 100:
            rating = "Very Strong"
            color = "#10b981"
            bg = "rgba(16, 185, 129, 0.12)"
        elif entropy > 64:
            rating = "Strong"
            color = "#06b6d4"
            bg = "rgba(6, 182, 212, 0.12)"
        elif entropy > 40:
            rating = "Fair"
            color = "#f59e0b"
            bg = "rgba(245, 158, 11, 0.12)"
        else:
            rating = "Weak"
            color = "#f43f5e"
            bg = "rgba(244, 63, 94, 0.12)"
        self.entropy_badge.setText(f"{entropy} bits • {rating}")
        self.entropy_badge.setStyleSheet(f"font-size: 10px; color: {color}; font-weight: 600; background: {bg}; padding: 2px 6px; border-radius: 4px;")
        return pwd

    def _use_password(self) -> None:
        self.password_generated.emit(self.preview_output.text())


class CredentialsPanel(QWidget):
    log_requested = Signal(str, str)

    def __init__(self, vault: CredentialVaultService, import_export: CredentialImportExportService) -> None:
        super().__init__()
        self.vault = vault
        self.import_export = import_export
        self._projects: list[CredentialProject] = []
        self._items: list[CredentialItem] = []
        self._selected_item: CredentialItem | None = None
        self._active_kind_filter: str = "all"
        self._reveal_timer: QTimer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.timeout.connect(self._auto_hide_secret)

        self.stack = QStackedWidget()
        self.create_page = self._build_create_page()
        self.unlock_page = self._build_unlock_page()
        self.manager_page = self._build_manager_page()
        self.stack.addWidget(self.create_page)
        self.stack.addWidget(self.unlock_page)
        self.stack.addWidget(self.manager_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.refresh()

    def refresh(self) -> None:
        if not self.vault.is_configured():
            self.stack.setCurrentWidget(self.create_page)
            return
        if not self.vault.is_unlocked:
            self.stack.setCurrentWidget(self.unlock_page)
            return
        self.stack.setCurrentWidget(self.manager_page)
        self._load_projects()

    def _build_create_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("VaultCreatePage")
        page.setStyleSheet("QWidget#VaultCreatePage { background: #09090b; }")

        card = QFrame()
        card.setObjectName("UnlockCard")
        card.setFixedWidth(440)
        card.setStyleSheet("""
            QFrame#UnlockCard {
                background: #111114;
                border: 1px solid #1e1e24;
                border-radius: 12px;
                padding: 32px;
            }
            QFrame#UnlockCard QLabel {
                background: transparent;
                border: none;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 28, 24, 28)
        card_layout.setSpacing(14)

        icon_badge = QLabel()
        icon_badge.setPixmap(get_icon("shield", color="#6366f1", size=32).pixmap(32, 32))
        icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Create Encrypted Vault")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f4f4f5;")

        pill = QLabel("Argon2id + AES-256-GCM")
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet("font-size: 11px; font-weight: 600; color: #a5b4fc; background: rgba(99, 102, 241, 0.12); border-radius: 10px; padding: 3px 10px; margin: 0 auto;")

        body = QLabel("Set a master password to initialize your encrypted local vault. This password will never leave your machine.")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet("color: #71717a; font-size: 12px; line-height: 1.4;")

        self.create_password = QLineEdit()
        self.create_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.create_password.setPlaceholderText("Enter master password (min 6 characters)...")
        self.create_password.setStyleSheet("QLineEdit { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 8px 12px; color: #f4f4f5; font-size: 13px; } QLineEdit:focus { border-color: #6366f1; }")

        self.create_confirm = QLineEdit()
        self.create_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.create_confirm.setPlaceholderText("Confirm master password...")
        self.create_confirm.setStyleSheet("QLineEdit { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 8px 12px; color: #f4f4f5; font-size: 13px; } QLineEdit:focus { border-color: #6366f1; }")

        create_btn = QPushButton("Create Encrypted Vault")
        create_btn.setObjectName("PrimaryButton")
        create_btn.setIcon(get_icon("shield", color="#ffffff", size=16))
        create_btn.setFixedHeight(38)
        create_btn.setStyleSheet("QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; border-radius: 6px; font-size: 13px; } QPushButton:hover { background: #4f46e5; }")

        card_layout.addWidget(icon_badge)
        card_layout.addWidget(title)
        card_layout.addWidget(pill, alignment=Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(body)
        card_layout.addSpacing(8)
        card_layout.addWidget(QLabel("Master Password:"))
        card_layout.addWidget(self.create_password)
        card_layout.addWidget(QLabel("Confirm Password:"))
        card_layout.addWidget(self.create_confirm)
        card_layout.addSpacing(10)
        card_layout.addWidget(create_btn)

        layout = QVBoxLayout(page)
        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        create_btn.clicked.connect(self._create_vault)
        self.create_confirm.returnPressed.connect(self._create_vault)
        return page

    def _build_unlock_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("VaultUnlockPage")
        page.setStyleSheet("QWidget#VaultUnlockPage { background: #09090b; }")

        card = QFrame()
        card.setObjectName("UnlockCard")
        card.setFixedWidth(420)
        card.setStyleSheet("""
            QFrame#UnlockCard {
                background: #111114;
                border: 1px solid #1e1e24;
                border-radius: 12px;
                padding: 32px;
            }
            QFrame#UnlockCard QLabel {
                background: transparent;
                border: none;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 28, 24, 28)
        card_layout.setSpacing(14)

        icon_badge = QLabel()
        icon_badge.setPixmap(get_icon("credentials", color="#6366f1", size=32).pixmap(32, 32))
        icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Unlock Credential Vault")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f4f4f5;")

        pill = QLabel("🔒 Vault is Locked")
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet("font-size: 11px; font-weight: 600; color: #f59e0b; background: rgba(245, 158, 11, 0.12); border-radius: 10px; padding: 3px 10px;")

        body = QLabel("Enter your master password to unlock projects, API tokens, and SSH keys.")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet("color: #71717a; font-size: 12px;")

        self.unlock_password = QLineEdit()
        self.unlock_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.unlock_password.setPlaceholderText("Master password...")
        self.unlock_password.setStyleSheet("QLineEdit { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 8px 12px; color: #f4f4f5; font-size: 13px; } QLineEdit:focus { border-color: #6366f1; }")

        unlock_btn = QPushButton("Unlock Vault")
        unlock_btn.setObjectName("PrimaryButton")
        unlock_btn.setIcon(get_icon("key", color="#ffffff", size=16))
        unlock_btn.setFixedHeight(38)
        unlock_btn.setStyleSheet("QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; border-radius: 6px; font-size: 13px; } QPushButton:hover { background: #4f46e5; }")

        card_layout.addWidget(icon_badge)
        card_layout.addWidget(title)
        card_layout.addWidget(pill, alignment=Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(body)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.unlock_password)
        card_layout.addSpacing(10)
        card_layout.addWidget(unlock_btn)

        layout = QVBoxLayout(page)
        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        unlock_btn.clicked.connect(self._unlock_vault)
        self.unlock_password.returnPressed.connect(self._unlock_vault)
        return page

    def _build_manager_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("VaultManagerPage")
        page.setStyleSheet("QWidget#VaultManagerPage { background: #09090b; }")

        # 1. Integrated Studio Header
        header = QFrame()
        header.setObjectName("VaultHeader")
        header.setStyleSheet("""
            QFrame#VaultHeader {
                background: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
            QFrame#VaultHeader QLabel {
                background: transparent;
                border: none;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(12)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        h_title = QLabel("Credential Vault Studio")
        h_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f4f4f5;")
        h_sub = QLabel("Argon2id KDF + AES-256-GCM encrypted local keystore")
        h_sub.setStyleSheet("font-size: 12px; color: #71717a;")
        header_text.addWidget(h_title)
        header_text.addWidget(h_sub)
        header_layout.addLayout(header_text)
        header_layout.addStretch()

        # Action Buttons
        self.btn_new_secret = QPushButton("New Secret")
        self.btn_new_secret.setIcon(get_icon("plus", color="#ffffff", size=14))
        self.btn_new_secret.setObjectName("PrimaryButton")
        self.btn_new_secret.setStyleSheet("QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; padding: 0 14px; height: 32px; border-radius: 6px; } QPushButton:hover { background: #4f46e5; }")

        self.btn_new_proj = QPushButton("+ New Project")
        self.btn_new_proj.setIcon(get_icon("folder", size=14))
        self.btn_new_proj.setStyleSheet("QPushButton { background: #18181b; color: #e4e4e7; border: 1px solid #27272a; padding: 0 12px; height: 32px; border-radius: 6px; } QPushButton:hover { background: #27272a; }")

        self.btn_actions_menu = QPushButton("Import / Export ▾")
        self.btn_actions_menu.setStyleSheet("QPushButton { background: #18181b; color: #e4e4e7; border: 1px solid #27272a; padding: 0 12px; height: 32px; border-radius: 6px; } QPushButton:hover { background: #27272a; }")
        self._build_actions_menu()

        self.btn_lock = QPushButton("Lock Vault")
        self.btn_lock.setIcon(get_icon("credentials", color="#f59e0b", size=14))
        self.btn_lock.setStyleSheet("QPushButton { background: rgba(245, 158, 11, 0.1); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); padding: 0 12px; height: 32px; border-radius: 6px; } QPushButton:hover { background: rgba(245, 158, 11, 0.2); }")

        header_layout.addWidget(self.btn_new_proj)
        header_layout.addWidget(self.btn_actions_menu)
        header_layout.addWidget(self.btn_lock)
        header_layout.addWidget(self.btn_new_secret)

        # 2. Main 3-Column Splitter
        studio_splitter = QSplitter(Qt.Orientation.Horizontal)
        studio_splitter.setHandleWidth(1)
        studio_splitter.setStyleSheet("QSplitter::handle { background: #1f222a; }")

        # -----------------------------
        # COLUMN 1: Projects Sidebar
        # -----------------------------
        col1 = QWidget()
        col1.setMinimumWidth(200)
        col1.setMaximumWidth(280)
        col1_layout = QVBoxLayout(col1)
        col1_layout.setContentsMargins(12, 12, 12, 12)
        col1_layout.setSpacing(8)

        col1_header = QLabel("PROJECTS")
        col1_header.setStyleSheet("font-size: 11px; font-weight: 700; color: #71717a; letter-spacing: 0.5px;")
        col1_layout.addWidget(col1_header)

        self.project_list = QListWidget()
        self.project_list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                color: #d4d4d8;
                outline: none;
            }
            QListWidget::item {
                height: 34px;
                padding-left: 8px;
                border-radius: 6px;
                margin-bottom: 2px;
                font-size: 13px;
            }
            QListWidget::item:hover {
                background: #18181b;
                color: #f4f4f5;
            }
            QListWidget::item:selected {
                background: #27272a;
                color: #ffffff;
                font-weight: 600;
                border-left: 3px solid #6366f1;
            }
        """)
        col1_layout.addWidget(self.project_list, 1)

        # Bottom actions for projects
        col1_bottom = QHBoxLayout()
        self.btn_del_project = QPushButton("Delete Project")
        self.btn_del_project.setIcon(get_icon("trash", size=13))
        self.btn_del_project.setStyleSheet("QPushButton { background: transparent; color: #71717a; border: none; font-size: 11px; text-align: left; } QPushButton:hover { color: #f43f5e; }")

        self.btn_chg_password = QPushButton("Change Master Password")
        self.btn_chg_password.setIcon(get_icon("settings", size=13))
        self.btn_chg_password.setStyleSheet("QPushButton { background: transparent; color: #71717a; border: none; font-size: 11px; text-align: left; } QPushButton:hover { color: #e4e4e7; }")

        col1_layout.addWidget(self.btn_chg_password)
        col1_layout.addWidget(self.btn_del_project)

        # -----------------------------
        # COLUMN 2: Secrets Catalog
        # -----------------------------
        col2 = QWidget()
        col2.setMinimumWidth(320)
        col2_layout = QVBoxLayout(col2)
        col2_layout.setContentsMargins(12, 12, 12, 12)
        col2_layout.setSpacing(10)

        # Search box
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search secrets, keys, tags, hosts...")
        self.search.setStyleSheet("QLineEdit { background: #121215; border: 1px solid #27272a; border-radius: 6px; padding: 7px 10px; color: #f4f4f5; font-size: 12px; } QLineEdit:focus { border-color: #6366f1; }")
        col2_layout.addWidget(self.search)

        # Filter Pills
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        self.filter_group = QButtonGroup(self)
        filters = [("All", "all"), ("API Keys", "api_key"), ("SSH", "ssh_key"), ("DB", "database"), (".env", "env"), ("★", "fav")]
        for label, code in filters:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("filter_code", code)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #71717a;
                    border: 1px solid #27272a;
                    border-radius: 12px;
                    padding: 3px 8px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    color: #e4e4e7;
                    border-color: #3f3f46;
                }
                QPushButton:checked {
                    background: #27272a;
                    color: #ffffff;
                    border-color: #6366f1;
                    font-weight: 600;
                }
            """)
            if code == "all":
                btn.setChecked(True)
            self.filter_group.addButton(btn)
            filter_row.addWidget(btn)
        filter_row.addStretch()
        col2_layout.addLayout(filter_row)

        # Items Table
        self.item_table = QTableWidget(0, 3)
        self.item_table.setHorizontalHeaderLabels(["Secret Title / User", "Kind", "Copy"])
        self.item_table.horizontalHeader().setStretchLastSection(False)
        self.item_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.item_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.item_table.setShowGrid(False)
        self.item_table.verticalHeader().setVisible(False)
        self.item_table.verticalHeader().setDefaultSectionSize(44)
        self.item_table.setStyleSheet("""
            QTableWidget {
                background: #121215;
                border: 1px solid #1f222a;
                border-radius: 8px;
                gridline-color: transparent;
                selection-background-color: #1f222a;
                color: #e4e4e7;
            }
            QHeaderView::section {
                background: #18181b;
                color: #71717a;
                border: none;
                border-bottom: 1px solid #27272a;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QTableWidget::item {
                border-bottom: 1px solid #1a1a1e;
                padding: 4px 8px;
            }
            QTableWidget::item:selected {
                background: #27272a;
                color: #ffffff;
            }
        """)
        col2_layout.addWidget(self.item_table, 1)

        # -----------------------------
        # COLUMN 3: Secret Inspector / Form
        # -----------------------------
        col3 = QWidget()
        col3_layout = QVBoxLayout(col3)
        col3_layout.setContentsMargins(12, 12, 12, 12)
        col3_layout.setSpacing(12)

        inspector_card = QFrame()
        inspector_card.setObjectName("InspectorCard")
        inspector_card.setStyleSheet("""
            QFrame#InspectorCard {
                background: #121215;
                border: 1px solid #1f222a;
                border-radius: 8px;
                padding: 16px;
            }
        """)
        insp_layout = QVBoxLayout(inspector_card)
        insp_layout.setContentsMargins(16, 16, 16, 16)
        insp_layout.setSpacing(10)

        # Inspector Title bar
        insp_header = QHBoxLayout()
        self.insp_title_label = QLabel("Secret Details")
        self.insp_title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #f4f4f5;")
        self.favorite_input = QCheckBox("★ Favorite")
        self.favorite_input.setStyleSheet("QCheckBox { color: #fbbf24; font-weight: 600; font-size: 12px; }")
        insp_header.addWidget(self.insp_title_label)
        insp_header.addStretch()
        insp_header.addWidget(self.favorite_input)
        insp_layout.addLayout(insp_header)

        # Form Inputs
        form_grid = QGridLayout()
        form_grid.setContentsMargins(0, 4, 0, 4)
        form_grid.setHorizontalSpacing(10)
        form_grid.setVerticalSpacing(8)

        # Title
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("e.g. AWS Production S3 Key")
        self._style_line_edit(self.title_input)

        # Kind
        self.kind_input = QComboBox()
        for kind, label in CREDENTIAL_KIND_LABELS.items():
            self.kind_input.addItem(label, kind.value)
        self.kind_input.setStyleSheet("QComboBox { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; }")

        form_grid.addWidget(QLabel("Title:"), 0, 0)
        form_grid.addWidget(self.title_input, 0, 1)
        form_grid.addWidget(QLabel("Kind:"), 0, 2)
        form_grid.addWidget(self.kind_input, 0, 3)

        # Username / Account + Copy
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username, client_id, account...")
        self._style_line_edit(self.username_input)
        self.copy_username_button = QPushButton("Copy")
        self._style_mini_btn(self.copy_username_button)
        u_box = QHBoxLayout()
        u_box.setContentsMargins(0, 0, 0, 0)
        u_box.addWidget(self.username_input, 1)
        u_box.addWidget(self.copy_username_button)

        # URL / Host + Copy
        self.url_host_input = QLineEdit()
        self.url_host_input.setPlaceholderText("Host, endpoint URL, or provider...")
        self._style_line_edit(self.url_host_input)
        self.copy_url_host_button = QPushButton("Copy")
        self._style_mini_btn(self.copy_url_host_button)
        h_box = QHBoxLayout()
        h_box.setContentsMargins(0, 0, 0, 0)
        h_box.addWidget(self.url_host_input, 1)
        h_box.addWidget(self.copy_url_host_button)

        form_grid.addWidget(QLabel("Account / User:"), 1, 0)
        form_grid.addLayout(u_box, 1, 1)
        form_grid.addWidget(QLabel("Host / URL:"), 1, 2)
        form_grid.addLayout(h_box, 1, 3)

        # Environment Key & Tags
        self.env_key_input = QLineEdit()
        self.env_key_input.setPlaceholderText("e.g. AWS_SECRET_ACCESS_KEY")
        self._style_line_edit(self.env_key_input)

        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("comma-separated tags: prod, aws, s3")
        self._style_line_edit(self.tags_input)

        form_grid.addWidget(QLabel("Env Variable:"), 2, 0)
        form_grid.addWidget(self.env_key_input, 2, 1)
        form_grid.addWidget(QLabel("Tags:"), 2, 2)
        form_grid.addWidget(self.tags_input, 2, 3)

        insp_layout.addLayout(form_grid)

        # Secret Value Section with Reveal Toggle and Copy
        secret_box = QVBoxLayout()
        secret_box.setSpacing(6)
        s_header = QHBoxLayout()
        s_lbl = QLabel("SECRET VALUE")
        s_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px;")
        self.reveal_status = QLabel("● Masked (AES-256-GCM)")
        self.reveal_status.setStyleSheet("font-size: 10px; color: #10b981;")

        self.btn_reveal_toggle = QPushButton("Reveal")
        self.btn_reveal_toggle.setIcon(get_icon("eye", size=14))
        self._style_mini_btn(self.btn_reveal_toggle)

        self.btn_copy_secret = QPushButton("Copy Secret")
        self.btn_copy_secret.setIcon(get_icon("copy", size=14))
        self._style_mini_btn(self.btn_copy_secret)

        s_header.addWidget(s_lbl)
        s_header.addWidget(self.reveal_status)
        s_header.addStretch()
        s_header.addWidget(self.btn_reveal_toggle)
        s_header.addWidget(self.btn_copy_secret)
        secret_box.addLayout(s_header)

        self.secret_input = QTextEdit()
        self.secret_input.setAcceptRichText(False)
        self.secret_input.setPlaceholderText("Enter or paste secret value (password, API token, private key)...")
        self.secret_input.setStyleSheet("QTextEdit { background: #0c0d10; color: #10b981; font-family: monospace; font-size: 12px; border: 1px solid #27272a; border-radius: 6px; padding: 6px; }")
        self.secret_input.setMaximumHeight(70)
        secret_box.addWidget(self.secret_input)
        insp_layout.addLayout(secret_box)

        # Built-in Password Generator Widget
        self.pw_generator = PasswordGeneratorWidget()
        insp_layout.addWidget(self.pw_generator)

        # Notes & Custom Fields Tabs or Stack
        notes_row = QHBoxLayout()
        notes_row.setSpacing(10)

        n_col = QVBoxLayout()
        n_col.addWidget(QLabel("Notes:"))
        self.notes_input = QTextEdit()
        self.notes_input.setAcceptRichText(False)
        self.notes_input.setPlaceholderText("Additional context, expiration dates, rotation notes...")
        self.notes_input.setStyleSheet("QTextEdit { background: #0c0d10; color: #e4e4e7; font-size: 12px; border: 1px solid #27272a; border-radius: 6px; padding: 6px; }")
        self.notes_input.setMaximumHeight(70)
        n_col.addWidget(self.notes_input)
        notes_row.addLayout(n_col, 1)

        c_col = QVBoxLayout()
        c_col.addWidget(QLabel("Custom Fields (KEY=VALUE):"))
        self.custom_fields_input = QTextEdit()
        self.custom_fields_input.setAcceptRichText(False)
        self.custom_fields_input.setPlaceholderText("PORT=5432\nREGION=us-east-1")
        self.custom_fields_input.setStyleSheet("QTextEdit { background: #0c0d10; color: #e4e4e7; font-family: monospace; font-size: 12px; border: 1px solid #27272a; border-radius: 6px; padding: 6px; }")
        self.custom_fields_input.setMaximumHeight(70)
        c_col.addWidget(self.custom_fields_input)
        notes_row.addLayout(c_col, 1)

        insp_layout.addLayout(notes_row)

        # Bottom Inspector Action Row
        bottom_actions = QHBoxLayout()
        self.btn_delete_secret = QPushButton("Delete")
        self.btn_delete_secret.setIcon(get_icon("trash", size=14))
        self.btn_delete_secret.setStyleSheet("QPushButton { background: transparent; color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.3); border-radius: 6px; height: 32px; padding: 0 12px; } QPushButton:hover { background: rgba(244, 63, 94, 0.15); }")

        self.btn_clear_form = QPushButton("Clear Form")
        self.btn_clear_form.setStyleSheet("QPushButton { background: #18181b; color: #a1a1aa; border: 1px solid #27272a; border-radius: 6px; height: 32px; padding: 0 12px; } QPushButton:hover { background: #27272a; color: #f4f4f5; }")

        self.btn_save_secret = QPushButton("Save Credential")
        self.btn_save_secret.setIcon(get_icon("check", size=14))
        self.btn_save_secret.setObjectName("PrimaryButton")
        self.btn_save_secret.setStyleSheet("QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; border-radius: 6px; height: 32px; padding: 0 18px; } QPushButton:hover { background: #4f46e5; }")

        bottom_actions.addWidget(self.btn_delete_secret)
        bottom_actions.addStretch()
        bottom_actions.addWidget(self.btn_clear_form)
        bottom_actions.addWidget(self.btn_save_secret)
        insp_layout.addLayout(bottom_actions)

        col3_scroll = QScrollArea()
        col3_scroll.setWidgetResizable(True)
        col3_scroll.setFrameShape(QFrame.Shape.NoFrame)
        col3_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        col3_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 4px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #27272a;
                border-radius: 2px;
            }
        """)
        col3_scroll.setWidget(inspector_card)
        col3_layout.addWidget(col3_scroll, 1)

        # Assemble Splitter
        studio_splitter.addWidget(col1)
        studio_splitter.addWidget(col2)
        studio_splitter.addWidget(col3)
        studio_splitter.setStretchFactor(0, 0)
        studio_splitter.setStretchFactor(1, 1)
        studio_splitter.setStretchFactor(2, 2)

        # Overall Layout
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(studio_splitter, 1)

        # Wire Signals
        self.project_list.currentRowChanged.connect(lambda _row: self._load_items())
        self.search.textChanged.connect(lambda _text: self._load_items())
        self.filter_group.buttonClicked.connect(self._on_filter_changed)
        self.item_table.itemSelectionChanged.connect(self._load_selected_item)
        self.btn_new_proj.clicked.connect(self._new_project)
        self.btn_del_project.clicked.connect(self._delete_project)
        self.btn_lock.clicked.connect(self._lock_vault)
        self.btn_chg_password.clicked.connect(self._change_master_password)
        self.btn_new_secret.clicked.connect(self._clear_item_form)
        self.btn_clear_form.clicked.connect(self._clear_item_form)
        self.btn_save_secret.clicked.connect(self._save_item)
        self.btn_delete_secret.clicked.connect(self._delete_item)
        self.btn_reveal_toggle.clicked.connect(self._toggle_reveal)
        self.btn_copy_secret.clicked.connect(self._copy_selected)
        self.copy_username_button.clicked.connect(lambda: self._copy_field_value(self.username_input, "Username"))
        self.copy_url_host_button.clicked.connect(lambda: self._copy_field_value(self.url_host_input, "URL/Host"))
        self.pw_generator.password_generated.connect(self._apply_generated_password)

        return page

    def _style_line_edit(self, edit: QLineEdit) -> None:
        edit.setStyleSheet("QLineEdit { background: #0c0d10; border: 1px solid #27272a; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 12px; } QLineEdit:focus { border-color: #6366f1; }")

    def _style_mini_btn(self, btn: QPushButton) -> None:
        btn.setStyleSheet("QPushButton { background: #18181b; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 0 8px; height: 26px; font-size: 11px; } QPushButton:hover { background: #27272a; color: #f4f4f5; }")

    def _build_actions_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #18181b;
                border: 1px solid #27272a;
                border-radius: 6px;
                padding: 4px;
                color: #e4e4e7;
            }
            QMenu::item {
                padding: 6px 20px 6px 10px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #27272a;
                color: #ffffff;
            }
        """)

        act_bulk = menu.addAction("Bulk Import (Text/Docs)...")
        act_bulk.triggered.connect(self._bulk_import)

        act_imp_env = menu.addAction("Import .env File...")
        act_imp_env.triggered.connect(self._import_env)

        act_exp_env = menu.addAction("Export .env File...")
        act_exp_env.triggered.connect(self._export_env)

        menu.addSeparator()

        act_imp_v = menu.addAction("Import Encrypted Vault...")
        act_imp_v.triggered.connect(self._import_vault)

        act_exp_v = menu.addAction("Export Encrypted Vault...")
        act_exp_v.triggered.connect(self._export_vault)

        self.btn_actions_menu.setMenu(menu)

    def _on_filter_changed(self, button: QPushButton) -> None:
        self._active_kind_filter = str(button.property("filter_code") or "all")
        self._load_items()

    def _apply_generated_password(self, pwd: str) -> None:
        self.secret_input.setPlainText(pwd)
        self.log_requested.emit("Generated secure password inserted into secret field.", "info")

    def _create_vault(self) -> None:
        if self.create_password.text() != self.create_confirm.text():
            QMessageBox.warning(self, "Password mismatch", "Master password and confirmation do not match.")
            return
        if len(self.create_password.text()) < 6:
            QMessageBox.warning(self, "Password too short", "Master password must be at least 6 characters.")
            return
        result = self.vault.create_vault(self.create_password.text())
        self._show_result(result)
        self.create_password.clear()
        self.create_confirm.clear()
        self.refresh()

    def _unlock_vault(self) -> None:
        result = self.vault.unlock(self.unlock_password.text())
        self._show_result(result)
        if result.ok:
            self.unlock_password.clear()
        self.refresh()

    def _lock_vault(self) -> None:
        self.vault.lock()
        self._clear_item_form()
        self.refresh()

    def _change_master_password(self) -> None:
        dialog = MasterPasswordDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        current, new = dialog.values()
        result = self.vault.change_master_password(current, new)
        self._show_result(result)
        self.refresh()

    def _load_projects(self) -> None:
        selected = self._selected_project_id()
        self._projects = self.vault.list_projects()
        self.project_list.clear()
        for project in self._projects:
            item = QListWidgetItem(project.name)
            item.setIcon(get_icon("folder", size=14))
            item.setData(USER_ROLE, project.id)
            self.project_list.addItem(item)
        if self._projects:
            row = next((idx for idx, project in enumerate(self._projects) if project.id == selected), 0)
            self.project_list.setCurrentRow(row)
        else:
            self._items = []
            self.item_table.setRowCount(0)

    def _load_items(self) -> None:
        project_id = self._selected_project_id()
        self._selected_item = None
        self._clear_item_form(clear_selection=False)
        self.item_table.setRowCount(0)
        if not project_id:
            return

        raw_items = self.vault.list_items(project_id, query=self.search.text())

        # Filter by kind or favorite
        if self._active_kind_filter == "fav":
            self._items = [i for i in raw_items if i.favorite]
        elif self._active_kind_filter == "api_key":
            self._items = [i for i in raw_items if i.kind == CredentialKind.API_KEY]
        elif self._active_kind_filter == "ssh_key":
            self._items = [i for i in raw_items if i.kind == CredentialKind.SSH_KEY]
        elif self._active_kind_filter == "database":
            self._items = [i for i in raw_items if i.kind == CredentialKind.DATABASE]
        elif self._active_kind_filter == "env":
            self._items = [i for i in raw_items if i.kind == CredentialKind.ENV]
        else:
            self._items = raw_items

        for credential in self._items:
            row = self.item_table.rowCount()
            self.item_table.insertRow(row)

            # Column 0: Title & User/Host
            title_text = credential.title
            if credential.favorite:
                title_text = f"★ {title_text}"
            sub = credential.environment_key or credential.username or credential.url_host or ""
            display_title = f"{title_text}\n{sub}" if sub else title_text

            title_item = QTableWidgetItem(display_title)
            title_item.setData(USER_ROLE, credential.id)

            # Column 1: Kind Pill
            kind_label = CREDENTIAL_KIND_LABELS.get(credential.kind, credential.kind.value)
            kind_item = QTableWidgetItem(kind_label)

            # Column 2: Copy Action Button
            copy_item = QTableWidgetItem("Copy")

            self.item_table.setItem(row, 0, title_item)
            self.item_table.setItem(row, 1, kind_item)
            self.item_table.setItem(row, 2, copy_item)

        self.item_table.resizeColumnsToContents()
        self.item_table.horizontalHeader().setStretchLastSection(False)
        if self.item_table.columnCount() > 0:
            self.item_table.horizontalHeader().setSectionResizeMode(0, self.item_table.horizontalHeader().ResizeMode.Stretch)

    def _load_selected_item(self) -> None:
        credential = self._selected_credential()
        self._selected_item = credential
        if credential is None:
            return
        self.insp_title_label.setText(credential.title)
        self.title_input.setText(credential.title)
        index = self.kind_input.findData(credential.kind.value)
        self.kind_input.setCurrentIndex(index if index >= 0 else 0)
        self.username_input.setText(credential.username)
        self.url_host_input.setText(credential.url_host)
        self.env_key_input.setText(credential.environment_key)
        self.tags_input.setText(format_tags(credential.tags))
        self.favorite_input.setChecked(credential.favorite)
        self.secret_input.clear()
        self.secret_input.setPlaceholderText("•••••••• (Hidden for security. Click 'Reveal' to view/edit).")
        self.btn_reveal_toggle.setText("Reveal")
        self.reveal_status.setText("● Masked (AES-256-GCM)")
        self.reveal_status.setStyleSheet("font-size: 10px; color: #10b981;")
        self.notes_input.clear()
        fields = self.vault.list_custom_fields(credential.id)
        self.custom_fields_input.setPlainText("\n".join(f"{field.name}=<hidden>" for field in fields))

    def _toggle_reveal(self) -> None:
        credential = self._selected_credential()
        if credential is None:
            return
        if self.btn_reveal_toggle.text() == "Hide":
            self._auto_hide_secret()
            return

        result = self.vault.reveal_secret(credential.id)
        if not result.ok:
            self._show_result(result)
            return

        self.secret_input.setPlainText(result.data)
        self.btn_reveal_toggle.setText("Hide")
        self.reveal_status.setText("● Revealed (Auto-hiding in 15s)")
        self.reveal_status.setStyleSheet("font-size: 10px; color: #f59e0b;")
        self._reveal_timer.start(15000)

    def _auto_hide_secret(self) -> None:
        if self._selected_item is not None:
            self.secret_input.clear()
            self.secret_input.setPlaceholderText("•••••••• (Hidden for security. Click 'Reveal' to view/edit).")
            self.btn_reveal_toggle.setText("Reveal")
            self.reveal_status.setText("● Masked (AES-256-GCM)")
            self.reveal_status.setStyleSheet("font-size: 10px; color: #10b981;")

    def _new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok or not name.strip():
            return
        result = self.vault.create_project(name.strip())
        self._show_result(result)
        self._load_projects()

    def _delete_project(self) -> None:
        project_id = self._selected_project_id()
        project = self._selected_project()
        if not project_id or project is None:
            return
        response = QMessageBox.warning(
            self,
            "Delete Project",
            f"Delete project '{project.name}' and all credentials inside it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        result = self.vault.delete_project(project_id)
        self._show_result(result)
        self._load_projects()

    def _save_item(self) -> None:
        project_id = self._selected_project_id()
        if not project_id:
            QMessageBox.information(self, "No project selected", "Create or select a project first.")
            return
        kind = CredentialKind(self.kind_input.currentData())
        secret = self.secret_input.toPlainText()
        if self._selected_item is not None and not secret:
            existing = self.vault.reveal_secret(self._selected_item.id, action="updated_preserve_secret")
            if not existing.ok:
                self._show_result(existing)
                return
            secret = existing.data
        elif self._selected_item is None and not secret:
            QMessageBox.warning(self, "Secret required", "Enter a secret value for this credential.")
            return
        common = {
            "secret_value": secret,
            "notes": self.notes_input.toPlainText(),
            "custom_fields": self._custom_fields_for_save(),
        }
        if self._selected_item is None:
            result = self.vault.add_item(
                project_id=project_id,
                title=self.title_input.text(),
                kind=kind,
                username=self.username_input.text(),
                url_host=self.url_host_input.text(),
                environment_key=self.env_key_input.text(),
                tags=parse_tags(self.tags_input.text()),
                favorite=self.favorite_input.isChecked(),
                **common,
            )
        else:
            self._selected_item.title = self.title_input.text().strip()
            self._selected_item.kind = kind
            self._selected_item.username = self.username_input.text().strip()
            self._selected_item.url_host = self.url_host_input.text().strip()
            self._selected_item.environment_key = self.env_key_input.text().strip()
            self._selected_item.tags = parse_tags(self.tags_input.text())
            self._selected_item.favorite = self.favorite_input.isChecked()
            result = self.vault.update_item(self._selected_item, **common)
        self._show_result(result)
        if result.ok:
            self._clear_item_form()
            self._load_items()

    def _delete_item(self) -> None:
        credential = self._selected_credential()
        if credential is None:
            return
        response = QMessageBox.question(self, "Delete Credential", f"Delete '{credential.title}'?")
        if response != QMessageBox.StandardButton.Yes:
            return
        result = self.vault.delete_item(credential.id)
        self._show_result(result)
        self._clear_item_form()
        self._load_items()

    def _copy_selected(self) -> None:
        credential = self._selected_credential()
        if credential is None:
            return
        result = self.vault.reveal_secret(credential.id, action="copied")
        if not result.ok:
            self._show_result(result)
            return
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(result.data)
        self.btn_copy_secret.setText("Copied!")
        QTimer.singleShot(2000, lambda: self.btn_copy_secret.setText("Copy Secret"))
        QTimer.singleShot(30000, lambda: clipboard.clear() if clipboard.text() == result.data else None)
        self.log_requested.emit(f"Copied credential '{credential.title}'. Clipboard will clear in 30 seconds.", "info")

    def _copy_field_value(self, field: QLineEdit, label: str) -> None:
        value = field.text().strip()
        if not value:
            QMessageBox.information(self, "Nothing to copy", f"No {label} value is available.")
            return
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(value)
        QTimer.singleShot(30000, lambda: clipboard.clear() if clipboard.text() == value else None)
        self.log_requested.emit(f"Copied {label}. Clipboard will clear in 30 seconds.", "info")

    def _import_env(self) -> None:
        project_id = self._selected_project_id()
        if not project_id:
            QMessageBox.information(self, "No project selected", "Create or select a project first.")
            return
        path, _filter = QFileDialog.getOpenFileName(self, "Import .env", str(Path.home()), "Environment files (*.env *);;All files (*)")
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8")
        preview = self.import_export.preview_env_import(project_id, text)
        response = QMessageBox.question(
            self,
            "Import .env",
            f"Import {preview.entries} entries?\nCreates: {preview.creates}\nUpdates: {preview.updates}",
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        result = self.import_export.import_env(project_id, text, conflict_policy="overwrite")
        self._show_result(result)
        self._load_items()

    def _bulk_import(self) -> None:
        project = self._selected_project()
        if project is None:
            QMessageBox.information(self, "No project selected", "Create or select a project first.")
            return
        dialog = BulkImportDialog(self.import_export, project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.result is not None:
            self._show_result(dialog.result)
        self._load_items()

    def _export_env(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        response = QMessageBox.warning(
            self,
            "Plaintext .env export",
            ".env exports are plaintext. Anyone with the file can read the secrets.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        result = self.import_export.export_env(project.id)
        if not result.ok:
            self._show_result(result)
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export .env", f"{project.name}.env", "Environment files (*.env);;All files (*)")
        if path:
            Path(path).write_text(result.data, encoding="utf-8")
            self.log_requested.emit(f"Exported .env for {project.name}.", "warning")

    def _export_vault(self) -> None:
        project_ids = [project.id for project in self._projects]
        if not project_ids:
            return
        password, ok = QInputDialog.getText(
            self,
            "Export encrypted vault",
            "Export password",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        result = self.import_export.export_encrypted(project_ids, password)
        if not result.ok:
            self._show_result(result)
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export vault", "credentials.rfm-vault", "RFM vault (*.rfm-vault);;All files (*)")
        if path:
            Path(path).write_text(result.data, encoding="utf-8")
            self.log_requested.emit("Encrypted credentials vault exported.", "info")

    def _import_vault(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Import vault", str(Path.home()), "RFM vault (*.rfm-vault);;All files (*)")
        if not path:
            return
        password, ok = QInputDialog.getText(
            self,
            "Import encrypted vault",
            "Export password",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        result = self.import_export.import_encrypted(Path(path).read_text(encoding="utf-8"), password)
        self._show_result(result)
        self._load_projects()

    def _custom_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        for raw in self.custom_fields_input.toPlainText().splitlines():
            if "=" not in raw:
                continue
            name, value = raw.split("=", 1)
            name = name.strip()
            if name:
                fields[name] = value
        return fields

    def _custom_fields_for_save(self) -> dict[str, str]:
        fields = self._custom_fields()
        if self._selected_item is None:
            return fields
        if not fields or all(value == "<hidden>" for value in fields.values()):
            existing = self.vault.reveal_custom_fields(self._selected_item.id)
            return dict(existing.data) if existing.ok else {}
        existing_values = self.vault.reveal_custom_fields(self._selected_item.id)
        existing = dict(existing_values.data) if existing_values.ok else {}
        for name, value in list(fields.items()):
            if value == "<hidden>" and name in existing:
                fields[name] = existing[name]
        return fields

    def _clear_item_form(self, *, clear_selection: bool = True) -> None:
        self._selected_item = None
        if clear_selection:
            self.item_table.clearSelection()
        self.insp_title_label.setText("New Credential")
        for widget in [
            self.title_input,
            self.username_input,
            self.url_host_input,
            self.env_key_input,
            self.tags_input,
        ]:
            widget.clear()
        self.kind_input.setCurrentIndex(0)
        self.favorite_input.setChecked(False)
        self.secret_input.clear()
        self.secret_input.setPlaceholderText("Enter or paste secret value...")
        self.btn_reveal_toggle.setText("Reveal")
        self.reveal_status.setText("● Masked (AES-256-GCM)")
        self.reveal_status.setStyleSheet("font-size: 10px; color: #10b981;")
        self.notes_input.clear()
        self.custom_fields_input.clear()

    def _selected_project_id(self) -> str | None:
        item = self.project_list.currentItem() if hasattr(self, "project_list") else None
        value = item.data(USER_ROLE) if item else None
        return str(value) if value else None

    def _selected_project(self) -> CredentialProject | None:
        selected = self._selected_project_id()
        return next((project for project in self._projects if project.id == selected), None)

    def _selected_credential(self) -> CredentialItem | None:
        rows = self.item_table.selectionModel().selectedRows()
        if not rows:
            return self._selected_item
        table_item = self.item_table.item(rows[0].row(), 0)
        item_id = table_item.data(USER_ROLE) if table_item else None
        return next((credential for credential in self._items if credential.id == item_id), None)

    def _show_result(self, result) -> None:  # type: ignore[no-untyped-def]
        level = "info" if result.ok else "error"
        self.log_requested.emit(result.message, level)
        if not result.ok:
            QMessageBox.warning(self, "Credentials", result.message)
