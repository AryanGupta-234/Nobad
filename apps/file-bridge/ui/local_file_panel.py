from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFileSystemModel,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeView,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QHeaderView
)

from file_ops.archive_models import ArchiveOperationRequest
from file_ops.archive_ops import LocalArchiveOperations, archive_format_for_path
from ui.archive_dialog import ArchiveDialog
from ui.async_worker import AsyncWorker
from ui.file_browser import FileTableWidget
from file_ops.metadata import local_file_item
from ui.icons import get_icon


class LocalFilePanel(QWidget):
    upload_requested = Signal(str)
    terminal_requested = Signal(str)
    edit_requested = Signal(str)
    path_changed = Signal(str)
    log_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.archive_ops = LocalArchiveOperations()
        self._workers: list[AsyncWorker] = []
        self.model = QFileSystemModel(self)
        self.model.setRootPath(QDir.homePath())
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)

        self.path_input = QLineEdit(QDir.homePath())
        self.path_input.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px;")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter...")
        self.search_input.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px;")
        self.search_input.setFixedWidth(140)
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(get_icon("sync", size=14))
        self.refresh_button.setToolTip("Refresh (F5)")
        self.refresh_button.setFixedSize(28, 28)
        self.up_button = QPushButton()
        self.up_button.setIcon(get_icon("upload", size=14))
        self.up_button.setToolTip("Parent directory")
        self.up_button.setFixedSize(28, 28)

        # Pane Header with Title: ● Local Files
        pane_title_box = QHBoxLayout()
        pane_title_box.setContentsMargins(0, 0, 0, 0)
        pane_title_box.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet("color: #71717a; font-size: 10px;")
        title = QLabel("Local Files")
        title.setStyleSheet("font-size: 12px; font-weight: 600; color: #f4f4f5;")
        pane_title_box.addWidget(dot)
        pane_title_box.addWidget(title)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(QDir.homePath()))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setIndentation(18)
        self.tree.setAnimated(True)
        tree_header = self.tree.header()
        tree_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tree_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        tree_header.resizeSection(1, 85)
        tree_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        tree_header.resizeSection(3, 140)
        self.tree.setColumnHidden(2, True)
        self.table = FileTableWidget()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.browser = QStackedWidget()
        self.browser.addWidget(self.table)
        self.browser.addWidget(self.tree)
        self._view_mode = "details"

        header_frame = QFrame()
        header_frame.setObjectName("PanelHeader")
        header_frame.setFixedHeight(38)
        header_frame.setStyleSheet("""
            QFrame#PanelHeader {
                background-color: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 4, 10, 4)
        header_layout.setSpacing(8)
        header_layout.addLayout(pane_title_box)
        header_layout.addWidget(self.up_button)
        header_layout.addWidget(self.path_input, 1)
        header_layout.addWidget(self.search_input)
        header_layout.addWidget(self.refresh_button)

        # Footer Status Bar
        self.footer = QFrame()
        self.footer.setObjectName("LocalFileFooter")
        self.footer.setFixedHeight(28)
        self.footer.setStyleSheet("""
            QFrame#LocalFileFooter {
                background-color: #111114;
                border: 0;
                border-top: 1px solid #1e1e24;
            }
        """)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(10, 0, 10, 0)
        self.footer_status = QLabel("Ready")
        self.footer_status.setStyleSheet("font-size: 11px; color: #71717a; font-family: 'JetBrains Mono', monospace;")
        self.upload_shortcut_lbl = QLabel("Upload to Remote (Alt+U)")
        self.upload_shortcut_lbl.setStyleSheet("font-size: 11px; color: #71717a;")
        footer_layout.addWidget(self.footer_status)
        footer_layout.addStretch()
        footer_layout.addWidget(self.upload_shortcut_lbl)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header_frame)
        layout.addWidget(self.browser, 1)
        layout.addWidget(self.footer)

        self.path_input.returnPressed.connect(self.navigate_to_input)
        self.search_input.textChanged.connect(self._filter_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.up_button.clicked.connect(self.go_up)
        self.tree.doubleClicked.connect(self._open_index)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.table.file_activated.connect(self._open_item)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.selectionModel().selectionChanged.connect(lambda *args: self._sync_footer())
        self._refresh_table()

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = "details" if mode == "details" else "tree"
        self.browser.setCurrentWidget(self.table if self._view_mode == "details" else self.tree)
        self._refresh_table()

    def current_path(self) -> str:
        return self.path_input.text()

    def navigate_to_input(self) -> None:
        self.set_path(self.path_input.text())

    def set_path(self, path: str) -> bool:
        target = Path(path).expanduser()
        if target.is_file():
            target = target.parent
        if not target.is_dir():
            return False
        resolved = str(target.resolve())
        self.path_input.setText(resolved)
        self.tree.setRootIndex(self.model.index(resolved))
        self._refresh_table()
        self.path_changed.emit(resolved)
        return True

    def refresh(self) -> None:
        self.model.setRootPath("")
        self.model.setRootPath(self.current_path())
        self._refresh_table()

    def _filter_changed(self, text: str) -> None:
        text = text.strip()
        if text:
            self.model.setNameFilters([f"*{text}*"])
            self.model.setNameFilterDisables(False)
        else:
            self.model.setNameFilters([])
        self.table.set_filter(text)

    def go_up(self) -> None:
        self.set_path(str(Path(self.current_path()).parent))

    def selected_path(self) -> str | None:
        if self._view_mode == "details":
            selected = self.table.selected_items_data()
            return selected[0].path if selected else None
        indexes = self.tree.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.model.filePath(indexes[0])

    def _open_index(self, index) -> None:  # type: ignore[no-untyped-def]
        path = self.model.filePath(index)
        if Path(path).is_dir():
            self.set_path(path)

    def _open_item(self, item) -> None:  # type: ignore[no-untyped-def]
        if item.is_dir:
            self.set_path(item.path)

    def _refresh_table(self) -> None:
        try:
            root = Path(self.current_path()).expanduser()
            items = [local_file_item(path) for path in sorted(root.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))]
        except OSError:
            items = []
        self.table.set_items(items)
        self._sync_footer()

    def _sync_footer(self) -> None:
        count = len(self.table.file_model.items)
        selected = len(self.table.selected_items_data())
        if selected > 0:
            self.footer_status.setText(f"{count} items • {selected} selected")
        else:
            self.footer_status.setText(f"{count} items")

    def _context_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        selected = self.selected_path()
        menu = QMenu(self)
        upload = menu.addAction("Upload selected")
        upload.setEnabled(selected is not None)
        edit = menu.addAction("Edit")
        edit.setEnabled(bool(selected and Path(selected).is_file()))
        terminal = menu.addAction("Open local terminal here")
        preview = menu.addAction("Preview archive")
        extract = menu.addAction("Extract archive")
        compress = menu.addAction("Compress")
        size = menu.addAction("Calculate folder size")
        preview.setEnabled(bool(selected and self._is_archive(selected)))
        extract.setEnabled(bool(selected and self._is_archive(selected)))
        compress.setEnabled(selected is not None)
        size.setEnabled(selected is not None)
        refresh = menu.addAction("Refresh")
        view = self.table if self._view_mode == "details" else self.tree
        action = menu.exec(view.viewport().mapToGlobal(position))
        if action == upload and selected:
            self.upload_requested.emit(selected)
        elif action == edit and selected:
            self.edit_requested.emit(selected)
        elif action == terminal:
            target = selected or self.current_path()
            path = Path(target)
            self.terminal_requested.emit(str(path if path.is_dir() else path.parent))
        elif action == preview and selected:
            self._preview_archive(selected)
        elif action == extract and selected:
            self._extract_archive(selected)
        elif action == compress and selected:
            self._compress_selected(selected)
        elif action == size and selected:
            self._calculate_size(selected)
        elif action == refresh:
            self.refresh()

    def _preview_archive(self, path: str) -> None:
        self._run(lambda: self.archive_ops.preview(path, destination=self.current_path()), self._show_archive_preview, self._show_archive_error)

    def _extract_archive(self, path: str) -> None:
        self._run(
            lambda: self.archive_ops.preview(path, destination=self.current_path()),
            lambda result: self._confirm_extract(path, result),
            self._show_archive_error,
        )

    def _compress_selected(self, path: str) -> None:
        default_path = str(Path(self.current_path()) / f"{Path(path).name}.zip")
        archive_path, _filter = QFileDialog.getSaveFileName(
            self,
            "Create archive",
            default_path,
            "Zip archive (*.zip);;Tar gzip archive (*.tar.gz)",
        )
        if not archive_path:
            return
        try:
            archive_format = archive_format_for_path(archive_path)
        except ValueError as exc:
            QMessageBox.warning(self, "Unsupported archive format", str(exc))
            return
        request = ArchiveOperationRequest(sources=[path], destination=archive_path, archive_format=archive_format)
        self._run(lambda: self.archive_ops.create(request), self._after_local_archive_mutation)

    def _calculate_size(self, path: str) -> None:
        self._run(lambda: self.archive_ops.calculate_folder_size(path), self._show_folder_size)

    def _confirm_extract(self, path: str, result) -> None:  # type: ignore[no-untyped-def]
        preview = result.data
        default_destination = str(Path(self.current_path()) / Path(path).stem.replace(".tar", ""))
        dialog = ArchiveDialog(
            title="Extract archive",
            preview=preview,
            path_label="Destination",
            default_path=default_destination,
            action_label="Extract",
            parent=self,
        )
        if dialog.exec() != ArchiveDialog.DialogCode.Accepted:
            return
        destination = dialog.selected_path()
        if not destination:
            QMessageBox.warning(self, "Missing destination", "Choose a destination folder.")
            return
        self._run(lambda: self.archive_ops.extract(path, destination), self._after_local_archive_mutation)

    def _show_archive_preview(self, result) -> None:  # type: ignore[no-untyped-def]
        ArchiveDialog(title="Archive preview", preview=result.data, action_label="Close", parent=self).exec()
        self.log_requested.emit(result.message, "info")

    def _show_archive_error(self, result) -> None:  # type: ignore[no-untyped-def]
        if result.data is not None:
            ArchiveDialog(title="Archive preview", preview=result.data, action_label="Close", parent=self).exec()
        QMessageBox.warning(self, "Archive operation failed", result.message)
        self.log_requested.emit(result.message, "error")

    def _after_local_archive_mutation(self, result) -> None:  # type: ignore[no-untyped-def]
        self.log_requested.emit(result.message, "info")
        QMessageBox.information(self, "Archive operation", result.message)
        self.refresh()

    def _show_folder_size(self, result) -> None:  # type: ignore[no-untyped-def]
        size = result.data
        QMessageBox.information(self, "Folder size", f"{size.path}\n\n{self._human_size(size.size_bytes)}")
        self.log_requested.emit(result.message, "info")

    def _run(self, factory, on_success, on_failure=None) -> None:  # type: ignore[no-untyped-def]
        worker = AsyncWorker(factory)
        self._workers.append(worker)
        worker.succeeded.connect(on_success)
        worker.failed.connect(on_failure or self._show_archive_error)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _is_archive(self, path: str) -> bool:
        try:
            archive_format_for_path(path)
            return True
        except ValueError:
            return False

    def _human_size(self, size: int) -> str:
        value = float(size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024 or unit == "TB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"
