from __future__ import annotations

import posixpath
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QStringListModel
from PySide6.QtWidgets import (
    QCompleter,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QDialog,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.result import OperationResult
from file_ops.archive_models import ArchiveOperationRequest, ArchiveFormat
from file_ops.archive_ops import LocalArchiveOperations, archive_format_for_path
from file_ops.remote_archive_ops import RemoteArchiveOperations
from file_ops.conflict_policy import ConflictDecision, ConflictPolicy
from file_ops.base import FileItem
from file_ops.safety import is_protected_remote_path
from ui.archive_dialog import ArchiveDialog
from ui.async_worker import AsyncRuntime, AsyncWorker
from ui.conflict_dialog import ConflictDialog
from ui.file_browser import FileTableWidget, FileTreeWidget
from ui.icons import get_icon
from transfers.transfer_job import TransferStatus


class RemoteFilePanel(QWidget):
    edit_requested = Signal(str)
    terminal_requested = Signal(str)
    log_requested = Signal(str, str)
    transfer_finished = Signal(object)
    copy_to_server_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.remote_ops = None
        self.connection = None
        self.archive_ops: RemoteArchiveOperations | None = None
        self.local_archive_ops = LocalArchiveOperations()
        self.transfer_manager = None
        self.transfer_queue_panel = None
        self.current_remote_path = "."
        self._initial_fallback_path: str | None = None
        self._workers: list[AsyncWorker] = []

        self.path_input = QLineEdit(".")
        self.path_input.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px;")
        self._path_completer_model = QStringListModel(self)
        self._path_completer = QCompleter(self._path_completer_model, self)
        self._path_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._path_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._path_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.path_input.setCompleter(self._path_completer)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter remote...")
        self.search_input.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px;")
        self.search_input.setFixedWidth(140)
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(get_icon("sync", size=14))
        self.refresh_button.setToolTip("Refresh (F5)")
        self.refresh_button.setFixedSize(28, 28)
        self.show_hidden_button = QPushButton()
        self.show_hidden_button.setIcon(get_icon("search", size=14))
        self.show_hidden_button.setToolTip("Show Hidden Files")
        self.show_hidden_button.setCheckable(True)
        self.show_hidden_button.setFixedSize(28, 28)
        self.up_button = QPushButton()
        self.up_button.setIcon(get_icon("upload", size=14))
        self.up_button.setToolTip("Parent directory")
        self.up_button.setFixedSize(28, 28)
        self.new_file_button = QPushButton()
        self.new_file_button.setIcon(get_icon("editor", size=14))
        self.new_file_button.setToolTip("New File")
        self.new_file_button.setFixedSize(28, 28)
        self.new_folder_button = QPushButton()
        self.new_folder_button.setIcon(get_icon("folder", size=14))
        self.new_folder_button.setToolTip("New Folder")
        self.new_folder_button.setFixedSize(28, 28)

        # Pane Header with Title: ● Remote: Not connected
        pane_title_box = QHBoxLayout()
        pane_title_box.setContentsMargins(0, 0, 0, 0)
        pane_title_box.setSpacing(6)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #71717a; font-size: 10px;")
        self.pane_title = QLabel("Remote: Not connected")
        self.pane_title.setStyleSheet("font-size: 12px; font-weight: 600; color: #a1a1aa;")
        pane_title_box.addWidget(self.status_dot)
        pane_title_box.addWidget(self.pane_title)

        self.table = FileTableWidget()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree = FileTreeWidget()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
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
        header_layout.setSpacing(6)
        header_layout.addLayout(pane_title_box)
        header_layout.addWidget(self.up_button)
        header_layout.addWidget(self.path_input, 1)
        header_layout.addWidget(self.search_input)
        header_layout.addWidget(self.refresh_button)
        header_layout.addWidget(self.show_hidden_button)
        header_layout.addWidget(self.new_file_button)
        header_layout.addWidget(self.new_folder_button)

        # Footer Status Bar
        self.footer = QFrame()
        self.footer.setObjectName("RemoteFileFooter")
        self.footer.setFixedHeight(28)
        self.footer.setStyleSheet("""
            QFrame#RemoteFileFooter {
                background-color: #111114;
                border: 0;
                border-top: 1px solid #1e1e24;
            }
        """)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(10, 0, 10, 0)
        self.footer_status = QLabel("Ready")
        self.footer_status.setStyleSheet("font-size: 11px; color: #71717a; font-family: 'JetBrains Mono', monospace;")
        self.download_shortcut_lbl = QLabel("Download to Local (Alt+D)")
        self.download_shortcut_lbl.setStyleSheet("font-size: 11px; color: #71717a;")
        footer_layout.addWidget(self.footer_status)
        footer_layout.addStretch()
        footer_layout.addWidget(self.download_shortcut_lbl)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header_frame)
        layout.addWidget(self.browser, 1)
        layout.addWidget(self.footer)

        self.refresh_button.clicked.connect(self.refresh)
        self.show_hidden_button.toggled.connect(self._toggle_hidden)
        self.up_button.clicked.connect(self.go_up)
        self.search_input.textChanged.connect(self.table.set_filter)
        self.search_input.textChanged.connect(self.tree.set_filter)
        self.path_input.returnPressed.connect(self.navigate_to_input)
        self.new_file_button.clicked.connect(self.create_file)
        self.new_folder_button.clicked.connect(self.create_folder)
        self.table.file_activated.connect(self._open_item)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.tree.file_activated.connect(self._open_item)
        self.tree.folder_expanded.connect(self._expand_tree_folder)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self._set_enabled(False)

    def set_remote_ops(self, remote_ops, *, initial_path: str = ".") -> None:  # type: ignore[no-untyped-def]
        self.remote_ops = remote_ops
        self.current_remote_path = initial_path.strip() or "."
        self.path_input.setText(self.current_remote_path)
        self._initial_fallback_path = "." if self.current_remote_path != "." else None
        self._set_enabled(True)
        self.refresh()

    def set_connection(self, connection) -> None:  # type: ignore[no-untyped-def]
        self.connection = connection
        self.archive_ops = RemoteArchiveOperations(connection)
        profile = getattr(connection, "profile", None)
        name = profile.name if profile else "Connected"
        self.pane_title.setText(f"Remote: {name}")
        self.pane_title.setStyleSheet("font-size: 12px; font-weight: 600; color: #f4f4f5;")
        self.status_dot.setStyleSheet("color: #10b981; font-size: 10px;")
        self.footer_status.setText("Connected")

    def clear_connection(self) -> None:
        self.connection = None
        self.remote_ops = None
        self.archive_ops = None
        self.current_remote_path = "."
        self._initial_fallback_path = None
        self.path_input.setText(".")
        self.table.set_items([])
        self.tree.set_items([])
        self._path_completer_model.setStringList([])
        self.pane_title.setText("Remote: Not connected")
        self.pane_title.setStyleSheet("font-size: 12px; font-weight: 600; color: #a1a1aa;")
        self.status_dot.setStyleSheet("color: #71717a; font-size: 10px;")
        self.footer_status.setText("Disconnected")
        self._set_enabled(False)

    def set_transfer_manager(self, transfer_manager, transfer_queue_panel) -> None:  # type: ignore[no-untyped-def]
        self.transfer_manager = transfer_manager
        self.transfer_queue_panel = transfer_queue_panel

    def _set_enabled(self, enabled: bool) -> None:
        for widget in [
            self.path_input,
            self.search_input,
            self.refresh_button,
            self.show_hidden_button,
            self.up_button,
            self.new_file_button,
            self.new_folder_button,
            self.table,
            self.tree,
        ]:
            widget.setEnabled(enabled)

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = "tree" if mode == "tree" else "details"
        self.browser.setCurrentWidget(self.tree if self._view_mode == "tree" else self.table)

    def navigate_to_input(self) -> None:
        self.current_remote_path = self.path_input.text().strip() or "."
        self._initial_fallback_path = None
        self.refresh()

    def refresh(self) -> None:
        if self.remote_ops is None:
            return
        path = self.current_remote_path
        show_hidden = self.show_hidden_button.isChecked()
        self._run(lambda: self.remote_ops.list_dir(path, show_hidden=show_hidden), self._on_listed)

    def go_up(self) -> None:
        self.current_remote_path = posixpath.dirname(self.current_remote_path.rstrip("/")) or "."
        self.path_input.setText(self.current_remote_path)
        self.refresh()

    def _toggle_hidden(self, checked: bool) -> None:
        self.show_hidden_button.setText("Hide Hidden" if checked else "Show Hidden")
        self.refresh()

    def create_file(self) -> None:
        name, ok = QInputDialog.getText(self, "Create remote file", "File name")
        if ok and name:
            self._run(lambda: self.remote_ops.create_file(posixpath.join(self.current_remote_path, name)), self._after_mutation)

    def create_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "Create remote folder", "Folder name")
        if ok and name:
            self._run(lambda: self.remote_ops.create_folder(posixpath.join(self.current_remote_path, name)), self._after_mutation)

    def upload_path(self, local_path: str) -> None:
        if self.remote_ops is None:
            return
        source = Path(local_path)
        if not source.exists():
            QMessageBox.warning(self, "Upload unavailable", "The selected local item no longer exists.")
            return
        destination = posixpath.join(self.current_remote_path, source.name)
        self._run_conflict_preflight(
            lambda: self._remote_destination_has_conflict(source, destination),
            lambda has_conflict: self._enqueue_upload(source, destination, has_conflict),
        )

    def _enqueue_upload(self, source: Path, destination: str, has_conflict: bool) -> None:
        decision = self._conflict_decision_for_preflight(has_conflict)
        if decision is None:
            return
        if source.is_dir():
            if self.transfer_manager is None:
                QMessageBox.warning(self, "Transfer unavailable", "Transfer manager is not available.")
                return
            jobs = self.transfer_manager.enqueue_upload_folder(
                self.remote_ops,
                local_folder=source,
                remote_folder=destination,
                conflict_decision=decision,
            )
            if not jobs:
                self.log_requested.emit("No files found to upload.", "info")
                return
            self._start_transfer_queue()
            return
        if self.transfer_manager is None:
            self._run(lambda: self.remote_ops.upload_file(source, destination), self._after_mutation)
            return
        self.transfer_manager.enqueue_upload_file(
            self.remote_ops,
            local_path=source,
            remote_path=destination,
            conflict_decision=decision,
        )
        self._start_transfer_queue()

    def _context_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        item = self._selected_single()
        menu = QMenu(self)
        upload = menu.addAction("Upload local file")
        download = menu.addAction("Download")
        edit = menu.addAction("Edit")
        rename = menu.addAction("Rename")
        delete = menu.addAction("Delete")
        terminal = menu.addAction("Open terminal here")
        chmod = menu.addAction("chmod")
        preview_archive = menu.addAction("Preview archive")
        compress = menu.addAction("Compress")
        extract = menu.addAction("Extract archive")
        folder_size = menu.addAction("Calculate folder size")
        copy_to_server = menu.addAction("Copy to Server...")
        refresh = menu.addAction("Refresh")
        for action in [download, edit, rename, delete]:
            action.setEnabled(item is not None)
        terminal.setEnabled(bool(item and self.connection and self.connection.capabilities.can_terminal))
        chmod.setEnabled(item is not None and self._can_chmod())
        archive_enabled = item is not None and self._can_remote_archive()
        preview_archive.setEnabled(bool(archive_enabled and item and self._is_archive(item.path)))
        extract.setEnabled(bool(archive_enabled and item and self._is_archive(item.path)))
        compress.setEnabled(bool(archive_enabled and item))
        folder_size.setEnabled(bool(item and item.is_dir and self._can_folder_size()))
        copy_to_server.setEnabled(item is not None)
        view = self.tree if self._view_mode == "tree" else self.table
        action = menu.exec(view.viewport().mapToGlobal(position))
        if action == upload:
            local_file, _ = QFileDialog.getOpenFileName(self, "Upload file")
            if local_file:
                self.upload_path(local_file)
        elif action == download and item:
            self._download(item)
        elif action == edit and item:
            self.edit_requested.emit(item.path)
        elif action == rename and item:
            self._rename(item)
        elif action == delete and item:
            self._delete(item)
        elif action == terminal and item:
            self.terminal_requested.emit(item.path if item.is_dir else self.current_remote_path)
        elif action == chmod and item:
            self._chmod(item)
        elif action == preview_archive and item:
            self._preview_remote_archive(item)
        elif action == compress and item:
            self._compress_remote_item(item)
        elif action == extract and item:
            self._extract_remote_archive(item)
        elif action == folder_size and item:
            self._calculate_remote_size(item)
        elif action == copy_to_server and item:
            self.copy_to_server_requested.emit(item)
        elif action == refresh:
            self.refresh()

    def _download(self, item: FileItem) -> None:
        target_dir = QFileDialog.getExistingDirectory(self, "Download to")
        if not target_dir:
            return
        local_target = Path(target_dir) / item.name
        self._run_conflict_preflight(
            lambda: self._local_destination_has_conflict(item, local_target),
            lambda has_conflict: self._enqueue_download(item, local_target, has_conflict),
        )

    def _enqueue_download(self, item: FileItem, local_target: Path, has_conflict: bool) -> None:
        decision = self._conflict_decision_for_preflight(has_conflict)
        if decision is None:
            return
        if item.is_dir:
            if self.transfer_manager is None:
                self._run(lambda: self.remote_ops.download_folder_recursive(item.path, local_target), self._after_mutation)
                return
            worker = AsyncWorker(
                lambda: self.transfer_manager.enqueue_download_folder(
                    self.remote_ops,
                    remote_item=item,
                    local_folder=local_target,
                    conflict_decision=decision,
                )
            )
            self._workers.append(worker)
            worker.succeeded.connect(lambda _jobs: self._start_transfer_queue())
            worker.failed.connect(self._show_error)
            worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
            worker.start()
        else:
            if self.transfer_manager is None:
                self._run(lambda: self.remote_ops.download_file(item.path, local_target), self._after_mutation)
                return
            self.transfer_manager.enqueue_download_file(
                self.remote_ops,
                remote_item=item,
                local_path=local_target,
                conflict_decision=decision,
            )
            self._start_transfer_queue()

    def _conflict_decision_for_preflight(self, has_conflict: bool) -> ConflictDecision | None:
        if has_conflict:
            return self._transfer_conflict_decision()
        # A file which appears after the preflight is skipped safely rather than
        # silently overwritten. Existing non-conflicting targets proceed normally.
        return ConflictDecision(ConflictPolicy.SKIP)

    async def _remote_destination_has_conflict(self, source: Path, destination: str) -> OperationResult:
        paths: list[str]
        if source.is_file():
            paths = [destination]
        else:
            paths = [
                posixpath.join(destination, path.relative_to(source).as_posix())
                for path in source.rglob("*")
                if path.is_file()
            ]
        for remote_path in paths:
            result = await self.remote_ops.stat(remote_path)
            if result.ok:
                return OperationResult.success("Remote conflict preflight complete.", data=True)
            if not self._is_missing_result(result):
                return OperationResult.failure(
                    f"Could not check whether {remote_path} already exists.",
                    technical_details=result.technical_details or result.message,
                    retryable=result.retryable,
                )
        return OperationResult.success("Remote conflict preflight complete.", data=False)

    async def _local_destination_has_conflict(self, item: FileItem, local_target: Path) -> OperationResult:
        if item.is_file:
            return OperationResult.success("Local conflict preflight complete.", data=local_target.exists())
        files_result = await self._remote_tree_files(item.path)
        if not files_result.ok:
            return files_result
        for remote_item in files_result.data:
            relative = posixpath.relpath(remote_item.path, item.path)
            if (local_target / relative).exists():
                return OperationResult.success("Local conflict preflight complete.", data=True)
        return OperationResult.success("Local conflict preflight complete.", data=False)

    async def _remote_tree_files(self, root: str) -> OperationResult:
        files: list[FileItem] = []

        async def collect(folder: str) -> OperationResult:
            result = await self.remote_ops.list_dir(folder, show_hidden=True)
            if not result.ok:
                return result
            for child in result.data or []:
                if child.is_dir:
                    nested = await collect(child.path)
                    if not nested.ok:
                        return nested
                elif child.is_file:
                    files.append(child)
            return OperationResult.success("Remote folder listed.")

        result = await collect(root)
        if not result.ok:
            return OperationResult.failure(
                "Could not inspect the remote folder before downloading.",
                technical_details=result.technical_details or result.message,
                retryable=result.retryable,
            )
        return OperationResult.success("Remote file list complete.", data=files)

    def _run_conflict_preflight(self, factory, on_ready) -> None:  # type: ignore[no-untyped-def]
        worker = AsyncWorker(factory)
        self._workers.append(worker)
        worker.succeeded.connect(lambda result: on_ready(bool(result.data)))
        worker.failed.connect(self._show_error)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _is_missing_result(self, result: OperationResult) -> bool:
        text = f"{result.message} {result.technical_details or ''}".lower()
        return any(token in text for token in ("missing", "not found", "no such file", "does not exist"))

    def _rename(self, item: FileItem) -> None:
        name, ok = QInputDialog.getText(self, "Rename remote item", "New name", text=item.name)
        if ok and name and name != item.name:
            destination = posixpath.join(posixpath.dirname(item.path), name)
            self._run(lambda: self.remote_ops.rename(item.path, destination), self._after_mutation)

    def _delete(self, item: FileItem) -> None:
        if is_protected_remote_path(item.path):
            QMessageBox.warning(self, "Protected path", f"Refusing dangerous operation on protected path:\n{item.path}")
            return
        response = QMessageBox.question(
            self,
            "Delete remote item",
            f"Delete {item.path}?\n\nThis may not be reversible.",
        )
        if response == QMessageBox.StandardButton.Yes:
            self._run(lambda: self.remote_ops.delete(item.path, recursive=item.is_dir), self._after_mutation)

    def _chmod(self, item: FileItem) -> None:
        if not self._can_chmod() or self.connection is None:
            return
        mode, ok = QInputDialog.getText(self, "chmod", "Octal mode", text="755")
        mode = mode.strip()
        if not ok:
            return
        if not self._valid_octal_mode(mode):
            QMessageBox.warning(self, "Invalid chmod mode", "Use a 3 or 4 digit octal mode, for example 644 or 0755.")
            return
        self._run(lambda: self.connection.run_command(f"chmod {mode} {self._sh_quote(item.path)}"), self._after_mutation)

    def _preview_remote_archive(self, item: FileItem) -> None:
        if self.archive_ops is None:
            return
        self._run(
            lambda: self.archive_ops.preview(item.path, destination=self.current_remote_path),
            self._show_remote_archive_preview,
            lambda result: self._remote_archive_error(result, "preview", item),
        )

    def _compress_remote_item(self, item: FileItem) -> None:
        if self.archive_ops is None:
            return
        default_archive = posixpath.join(posixpath.dirname(item.path), f"{item.name}.zip")
        archive_path, ok = QInputDialog.getText(self, "Create remote archive", "Archive path", text=default_archive)
        archive_path = archive_path.strip()
        if not ok or not archive_path:
            return
        try:
            archive_format = archive_format_for_path(archive_path)
        except ValueError as exc:
            QMessageBox.warning(self, "Unsupported archive format", str(exc))
            return
        request = ArchiveOperationRequest(sources=[item.path], destination=archive_path, archive_format=archive_format)
        self._run(
            lambda: self.archive_ops.create(request),
            self._after_mutation,
            lambda result: self._remote_archive_error(result, "create", item, archive_path=archive_path, archive_format=archive_format),
        )

    def _extract_remote_archive(self, item: FileItem) -> None:
        if self.archive_ops is None:
            return
        self._run(
            lambda: self.archive_ops.preview(item.path, destination=self.current_remote_path),
            lambda result: self._confirm_remote_extract(item, result),
            lambda result: self._remote_archive_error(result, "extract", item),
        )

    def _calculate_remote_size(self, item: FileItem) -> None:
        if self.archive_ops is None:
            return
        self._run(lambda: self.archive_ops.calculate_folder_size(item.path), self._show_remote_folder_size)

    def _confirm_remote_extract(self, item: FileItem, result: OperationResult) -> None:
        default_destination = posixpath.join(posixpath.dirname(item.path), self._archive_stem(item.name))
        dialog = ArchiveDialog(
            title="Extract remote archive",
            preview=result.data,
            path_label="Destination",
            default_path=default_destination,
            action_label="Extract",
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination = dialog.selected_path()
        if not destination:
            QMessageBox.warning(self, "Missing destination", "Choose a remote destination folder.")
            return
        self._run(
            lambda: self.archive_ops.extract(item.path, destination),
            self._after_mutation,
            lambda failure: self._remote_archive_error(failure, "extract", item, destination=destination),
        )

    def _show_remote_archive_preview(self, result: OperationResult) -> None:
        ArchiveDialog(title="Remote archive preview", preview=result.data, action_label="Close", parent=self).exec()
        self.log_requested.emit(result.message, "info")

    def _show_remote_folder_size(self, result: OperationResult) -> None:
        size = result.data
        QMessageBox.information(self, "Remote folder size", f"{size.path}\n\n{self._human_size(size.size_bytes)}")
        self.log_requested.emit(result.message, "info")

    def _remote_archive_error(
        self,
        result: OperationResult,
        operation: str,
        item: FileItem,
        *,
        destination: str | None = None,
        archive_path: str | None = None,
        archive_format: ArchiveFormat | None = None,
    ) -> None:
        if result.data is not None:
            ArchiveDialog(title="Remote archive preview", preview=result.data, action_label="Close", parent=self).exec()
        if "Remote command unavailable" in result.message:
            response = QMessageBox.question(
                self,
                "Use local relay?",
                f"{result.message}\n\nUse local relay mode through this computer instead?",
            )
            if response == QMessageBox.StandardButton.Yes:
                self.log_requested.emit("Local relay chosen for archive operation.", "info")
                self._start_local_relay(operation, item, destination=destination, archive_path=archive_path, archive_format=archive_format)
                return
        self._show_error(result)

    def _start_local_relay(
        self,
        operation: str,
        item: FileItem,
        *,
        destination: str | None = None,
        archive_path: str | None = None,
        archive_format: ArchiveFormat | None = None,
    ) -> None:
        if operation == "preview":
            self._run(lambda: self._local_relay_preview(item), self._show_remote_archive_preview)
        elif operation == "extract" and destination:
            self._run(lambda: self._local_relay_extract(item, destination), self._after_mutation)
        elif operation == "create" and archive_path and archive_format:
            self._run(lambda: self._local_relay_create(item, archive_path, archive_format), self._after_mutation)

    async def _local_relay_preview(self, item: FileItem) -> OperationResult:
        with tempfile.TemporaryDirectory(prefix="rfm-archive-preview-") as folder:
            local_archive = Path(folder) / item.name
            download = await self.remote_ops.download_file(item.path, local_archive)
            if not download.ok:
                return download
            return await self.local_archive_ops.preview(local_archive, destination=folder)

    async def _local_relay_extract(self, item: FileItem, destination: str) -> OperationResult:
        with tempfile.TemporaryDirectory(prefix="rfm-archive-extract-") as folder:
            root = Path(folder)
            local_archive = root / item.name
            extract_root = root / "extract"
            download = await self.remote_ops.download_file(item.path, local_archive)
            if not download.ok:
                return download
            extract = await self.local_archive_ops.extract(local_archive, extract_root)
            if not extract.ok:
                return extract
            ensure = await self.remote_ops.ensure_folder(destination)
            if not ensure.ok:
                return ensure
            if self.transfer_manager is not None:
                jobs = self.transfer_manager.enqueue_upload_folder(
                    self.remote_ops,
                    local_folder=extract_root,
                    remote_folder=destination,
                    conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
                )
                await self.transfer_manager.run_until_idle()
                failed = [job for job in jobs if job.status != TransferStatus.COMPLETED]
                if failed:
                    return OperationResult.failure("Local relay extraction upload failed.", technical_details=failed[0].error_message)
            else:
                for file in [path for path in extract_root.rglob("*") if path.is_file()]:
                    remote_target = posixpath.join(destination, file.relative_to(extract_root).as_posix())
                    await self.remote_ops.ensure_folder(posixpath.dirname(remote_target))
                    upload = await self.remote_ops.upload_file(file, remote_target)
                    if not upload.ok:
                        return upload
            return OperationResult.success("Local relay extraction completed.", affected_paths=[item.path, destination])

    async def _local_relay_create(self, item: FileItem, archive_path: str, archive_format: ArchiveFormat) -> OperationResult:
        with tempfile.TemporaryDirectory(prefix="rfm-archive-create-") as folder:
            root = Path(folder)
            local_source = root / item.name
            if item.is_dir:
                download = await self.remote_ops.download_folder_recursive(item.path, local_source)
            else:
                download = await self.remote_ops.download_file(item.path, local_source)
            if not download.ok:
                return download
            local_archive = root / Path(archive_path).name
            create = await self.local_archive_ops.create(
                ArchiveOperationRequest(sources=[local_source], destination=local_archive, archive_format=archive_format)
            )
            if not create.ok:
                return create
            if self.transfer_manager is not None:
                job = self.transfer_manager.enqueue_upload_file(
                    self.remote_ops,
                    local_path=local_archive,
                    remote_path=archive_path,
                    conflict_decision=ConflictDecision(ConflictPolicy.OVERWRITE),
                )
                await self.transfer_manager.run_until_idle()
                if job.status != TransferStatus.COMPLETED:
                    return OperationResult.failure("Local relay archive upload failed.", technical_details=job.error_message)
            else:
                upload = await self.remote_ops.upload_file(local_archive, archive_path)
                if not upload.ok:
                    return upload
            return OperationResult.success("Local relay archive created.", affected_paths=[archive_path])

    def _open_item(self, item: FileItem) -> None:
        if item.is_dir:
            self.current_remote_path = item.path
            self.path_input.setText(item.path)
            self.refresh()
        else:
            self.edit_requested.emit(item.path)

    def _selected_single(self) -> FileItem | None:
        selected = (self.tree if self._view_mode == "tree" else self.table).selected_items_data()
        return selected[0] if selected else None

    def _on_listed(self, result: OperationResult) -> None:
        self._initial_fallback_path = None
        self.path_input.setText(self.current_remote_path)
        self.table.set_items(result.data or [])
        self.tree.set_items(result.data or [])
        self._update_path_completions(result.data or [])
        for warning in result.warnings:
            self.log_requested.emit(warning, "warning")

    def _expand_tree_folder(self, item: FileItem, node) -> None:  # type: ignore[no-untyped-def]
        if self.remote_ops is None:
            return
        self._run(
            lambda: self.remote_ops.list_dir(item.path, show_hidden=self.show_hidden_button.isChecked()),
            lambda result: self.tree.set_children(node, result.data or []),
        )

    def _update_path_completions(self, items: list[FileItem]) -> None:
        directories = [item.path for item in items if item.is_dir]
        directories.sort(key=lambda value: value.lower())
        if self.current_remote_path and self.current_remote_path not in {".", ""}:
            if self.current_remote_path not in directories:
                directories.insert(0, self.current_remote_path)
        self._path_completer_model.setStringList(directories)

    def _after_mutation(self, result: OperationResult) -> None:
        self.log_requested.emit(result.message, "info" if result.ok else "error")
        self.refresh()

    def _run(self, factory, on_success) -> None:  # type: ignore[no-untyped-def]
        worker = AsyncWorker(factory)
        self._workers.append(worker)
        worker.succeeded.connect(on_success)
        worker.failed.connect(self._show_error)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _start_transfer_queue(self) -> None:
        if self.transfer_manager is None:
            return
        AsyncRuntime.instance().submit(self.transfer_manager.run_until_idle())

    def _transfer_conflict_decision(self) -> ConflictDecision | None:
        dialog = ConflictDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        decision = dialog.selected_decision()
        if decision.policy == ConflictPolicy.RENAME:
            return ConflictDecision(ConflictPolicy.RENAME, apply_to_all=decision.apply_to_all)
        return decision

    def _can_chmod(self) -> bool:
        return bool(self.connection and self.connection.capabilities.can_chmod)

    def _can_remote_archive(self) -> bool:
        return bool(self.connection and self.connection.capabilities.can_exec_command)

    def _can_folder_size(self) -> bool:
        return bool(self.connection and self.connection.capabilities.can_calculate_size)

    def _valid_octal_mode(self, mode: str) -> bool:
        return len(mode) in {3, 4} and all(char in "01234567" for char in mode)

    def _sh_quote(self, value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    def _is_archive(self, path: str) -> bool:
        try:
            archive_format_for_path(path)
            return True
        except ValueError:
            return False

    def _archive_stem(self, name: str) -> str:
        lowered = name.lower()
        if lowered.endswith(".tar.gz"):
            return name[:-7]
        if lowered.endswith(".tgz"):
            return name[:-4]
        if lowered.endswith(".zip"):
            return name[:-4]
        return name

    def _human_size(self, size: int) -> str:
        value = float(size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024 or unit == "TB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _show_error(self, result: OperationResult) -> None:
        if self._initial_fallback_path is not None:
            failed_path = self.current_remote_path
            fallback = self._initial_fallback_path
            self._initial_fallback_path = None
            self.current_remote_path = fallback
            self.path_input.setText(fallback)
            self.log_requested.emit(
                f"Default remote path {failed_path} could not be opened. Falling back to the remote home directory.",
                "warning",
            )
            self.refresh()
            return
        self.log_requested.emit(result.message, "error")
        if result.technical_details:
            self.log_requested.emit(result.technical_details, "error")
        if result.suggested_fix:
            self.log_requested.emit(result.suggested_fix, "info")
        QMessageBox.warning(self, "Remote operation failed", self._format_error(result))

    def _format_error(self, result: OperationResult) -> str:
        parts = [result.message]
        if result.suggested_fix:
            parts.append(f"Suggested fix:\n{result.suggested_fix}")
        if result.technical_details:
            parts.append(result.technical_details)
        return "\n\n".join(parts)
