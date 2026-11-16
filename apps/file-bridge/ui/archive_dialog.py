from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout

from file_ops.archive_models import ArchivePreview
from file_ops.base import human_size


class ArchiveDialog(QDialog):
    def __init__(
        self,
        *,
        title: str = "Archive",
        preview: ArchivePreview | None = None,
        path_label: str | None = None,
        default_path: str = "",
        action_label: str = "OK",
        parent=None,
    ) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle(title)
        self.path_input = QLineEdit(default_path)
        self.summary = QLabel(self._summary_text(preview))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(self._details_text(preview))
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.action_button = self.buttons.addButton(action_label, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        if path_label is not None:
            form = QFormLayout()
            form.addRow(path_label, self.path_input)
            layout.addLayout(form)
        layout.addWidget(self.details)
        layout.addWidget(self.buttons)
        self.resize(620, 420)

        if preview is not None and not preview.safe and action_label.lower() != "close":
            self.action_button.setEnabled(False)

    def selected_path(self) -> str:
        return self.path_input.text().strip()

    def _summary_text(self, preview: ArchivePreview | None) -> str:
        if preview is None:
            return "Configure archive operation."
        size = human_size(preview.total_size)
        safe = "safe" if preview.safe else "unsafe"
        return f"{preview.format.value} archive, {preview.member_count} item(s), {size or 'unknown size'}, {safe}."

    def _details_text(self, preview: ArchivePreview | None) -> str:
        if preview is None:
            return ""
        lines: list[str] = []
        if preview.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in preview.warnings)
            lines.append("")
        lines.append("Members:")
        for member in preview.members[:1000]:
            size = human_size(member.size)
            suffix = " [link]" if member.is_link else ""
            lines.append(f"{member.name}{suffix}{f' ({size})' if size else ''}")
        if len(preview.members) > 1000:
            lines.append(f"... {len(preview.members) - 1000} more")
        return "\n".join(lines)
