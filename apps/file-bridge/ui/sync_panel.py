from __future__ import annotations

import asyncio
import hashlib
import posixpath
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFrame
)

from core.result import OperationResult
from file_ops.base import FileItem, human_size
from sync.diff_engine import SyncAction, SyncManifestEntry, SyncPlanEntry, SyncPreview
from sync.baseline_service import SyncBaselineService
from sync.conflicts import SyncConflictResolver
from sync.ignore_rules import DEFAULT_IGNORE_PATTERNS, should_ignore
from sync.sync_executor import SyncExecutionPolicy, SyncExecutionResult, SyncExecutor
from sync.sync_job import SyncJob, SyncMode
from sync.sync_planner import SyncPlanner
from ui.async_worker import AsyncWorker
from ui.diff_viewer import DiffViewerDialog
from ui.sync_conflict_dialog import SyncConflictDialog
from editor.encoding import is_probably_binary, detect_encoding
from core.connections.rsync_adapter import RsyncAdapter, RsyncDirection
from transfers.transfer_job import TransferDirection, TransferJob
from ui.icons import get_icon


USER_ROLE_JOB = int(Qt.ItemDataRole.UserRole)


class SyncPreviewTableModel(QAbstractTableModel):
    HEADERS = ["Action", "Path", "Reason", "Source Size", "Destination Size"]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[SyncPlanEntry] = []

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.entries)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return entry
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        values = [
            entry.action.value,
            entry.path,
            entry.reason,
            human_size(entry.source_size),
            human_size(entry.destination_size),
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def set_preview(self, preview: SyncPreview | None) -> None:
        self.beginResetModel()
        self.entries = list(preview.entries if preview else [])
        self.endResetModel()


class SyncPanel(QWidget):
    log_requested = Signal(str, str)
    save_requested = Signal(object)
    delete_requested = Signal(str)
    refresh_requested = Signal()
    execution_started = Signal()
    execution_finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.remote_ops = None
        self.transfer_manager = None
        self._jobs: list[SyncJob] = []
        self._workers: list[AsyncWorker] = []
        self.planner = SyncPlanner()
        self.executor = SyncExecutor()
        self.conflict_resolver = SyncConflictResolver()
        self.baseline_service: SyncBaselineService | None = None
        self.profile_id: str | None = None
        self.connection = None
        self.rsync_adapter: RsyncAdapter | None = None
        self.saved_jobs = QComboBox()
        self.saved_jobs.addItem("New sync preview", None)
        self.job_name = QLineEdit()
        self.job_name.setPlaceholderText("Sync name")
        self.mode = QComboBox()
        self.mode.addItem("Upload local to remote", SyncMode.LOCAL_TO_REMOTE)
        self.mode.addItem("Download remote to local", SyncMode.REMOTE_TO_LOCAL)
        self.mode.addItem("Two-way preview", SyncMode.TWO_WAY)
        self.transfer_engine = QComboBox()
        self.transfer_engine.addItem("Transfer queue", "queue")
        self.transfer_engine.addItem("rsync acceleration", "rsync")
        self.local_path = QLineEdit(str(Path.home()))
        self.remote_path = QLineEdit(".")
        self.ignore_patterns = QTextEdit(", ".join(DEFAULT_IGNORE_PATTERNS))
        self.ignore_patterns.setMaximumHeight(58)
        self.browse_local = QPushButton("Browse")
        self.preview_button = QPushButton("Preview")
        self.preview_button.setObjectName("PrimaryButton")
        self.preview_button.setIcon(get_icon("search", size=14))
        self.save_button = QPushButton("Save Job")
        self.save_button.setIcon(get_icon("folder", size=14))
        self.delete_button = QPushButton("Delete")
        self.delete_button.setIcon(get_icon("cancel", size=14))
        self.execute_button = QPushButton("Execute")
        self.execute_button.setIcon(get_icon("sync", size=14))
        self.execute_button.setEnabled(False)
        self.status = QLabel("Preview a sync before any destructive execution exists.")
        self.status.setObjectName("MutedLabel")
        self.model = SyncPreviewTableModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setStretchLastSection(True)

        # Modern Header Frame
        header = QFrame()
        header.setObjectName("SyncHeader")
        header.setStyleSheet("""
            QFrame#SyncHeader {
                background: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
            QFrame#SyncHeader QLabel {
                background: transparent;
                border: none;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(10)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        h_title = QLabel("Directory Sync Studio")
        h_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f4f4f5;")
        h_sub = QLabel("Bi-directional folder comparison, rsync acceleration, and conflict resolution")
        h_sub.setStyleSheet("font-size: 12px; color: #71717a;")
        header_text.addWidget(h_title)
        header_text.addWidget(h_sub)
        header_layout.addLayout(header_text)
        header_layout.addStretch()

        job_lbl = QLabel("Job:")
        job_lbl.setStyleSheet("background: transparent; border: none; color: #a1a1aa;")
        header_layout.addWidget(job_lbl)
        self.saved_jobs.setMinimumWidth(180)
        header_layout.addWidget(self.saved_jobs)
        header_layout.addWidget(self.save_button)
        header_layout.addWidget(self.delete_button)

        # Config Card Frame
        config_card = QFrame()
        config_card.setObjectName("SyncConfigCard")
        config_card.setStyleSheet("""
            QFrame#SyncConfigCard {
                background: #111114;
                border: 1px solid #1e1e24;
                border-radius: 8px;
            }
            QFrame#SyncConfigCard QLabel {
                background: transparent;
                border: none;
            }
        """)
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(12, 10, 12, 10)
        config_layout.setSpacing(8)
        config_layout.addLayout(self._form_layout())

        self.table.setStyleSheet("""
            QTableView {
                background: #121215;
                border: 1px solid #1e1e24;
                border-radius: 8px;
                gridline-color: transparent;
                selection-background-color: #1e1e24;
                color: #e4e4e7;
            }
            QHeaderView {
                background: #18181b;
                border: none;
            }
            QHeaderView::section {
                background: #18181b;
                color: #71717a;
                border: none;
                border-bottom: 1px solid #1e1e24;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QTableView::item {
                border-bottom: 1px solid #1a1a1e;
                padding: 4px 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)
        body_layout.addWidget(config_card)
        body_layout.addLayout(self._action_bar())
        body_layout.addWidget(self.status)
        body_layout.addWidget(self.table, 1)

        layout.addWidget(body, 1)

        self.saved_jobs.currentIndexChanged.connect(self._load_selected_job)
        self.mode.currentIndexChanged.connect(self._sync_engine_enabled)
        self.browse_local.clicked.connect(self._browse_local)
        self.preview_button.clicked.connect(self.preview)
        self.save_button.clicked.connect(self._save_current_job)
        self.delete_button.clicked.connect(self._delete_selected_job)
        self.execute_button.clicked.connect(self.execute)

    def set_remote_ops(self, remote_ops, profile_id: str | None = None) -> None:  # type: ignore[no-untyped-def]
        self.remote_ops = remote_ops
        self.profile_id = profile_id
        self.status.setText("Sync preview ready for the active remote connection.")
        self._sync_execute_enabled()

    def set_transfer_manager(self, transfer_manager) -> None:  # type: ignore[no-untyped-def]
        self.transfer_manager = transfer_manager
        self._sync_execute_enabled()

    def set_connection(self, connection, rsync_adapter: RsyncAdapter | None = None) -> None:  # type: ignore[no-untyped-def]
        self.connection = connection
        self.rsync_adapter = rsync_adapter
        self._sync_engine_enabled()

    def set_baseline_service(self, service: SyncBaselineService) -> None:
        self.baseline_service = service

    def clear_connection(self) -> None:
        self.remote_ops = None
        self.profile_id = None
        self.connection = None
        self.status.setText("Connect to an SSH/SFTP server before previewing remote sync.")
        self.model.set_preview(None)
        self._sync_execute_enabled()

    def set_saved_jobs(self, jobs: list[SyncJob]) -> None:
        current_id = self._selected_job_id()
        self._jobs = jobs
        self.saved_jobs.blockSignals(True)
        self.saved_jobs.clear()
        self.saved_jobs.addItem("New sync preview", None)
        for job in jobs:
            self.saved_jobs.addItem(job.name, job)
        if current_id:
            for index in range(self.saved_jobs.count()):
                job = self.saved_jobs.itemData(index, USER_ROLE_JOB)
                if getattr(job, "id", None) == current_id:
                    self.saved_jobs.setCurrentIndex(index)
                    break
        self.saved_jobs.blockSignals(False)

    def set_default_paths(self, local_path: str | None = None, remote_path: str | None = None) -> None:
        if local_path and not self.local_path.text().strip():
            self.local_path.setText(local_path)
        if remote_path and self.remote_path.text().strip() in {"", "."}:
            self.remote_path.setText(remote_path)

    def preview(self) -> None:
        job = self.current_job()
        if not job.source_path or not job.destination_path:
            QMessageBox.warning(self, "Missing sync paths", "Choose both local and remote paths before previewing.")
            return
        if self.remote_ops is None:
            QMessageBox.information(self, "Sync unavailable", "Connect to an SSH/SFTP server before previewing sync.")
            return
        self.preview_button.setEnabled(False)
        self.status.setText("Building sync preview...")
        worker = AsyncWorker(lambda: self._build_preview(job))
        self._workers.append(worker)
        worker.succeeded.connect(self._show_preview)
        worker.failed.connect(self._show_error)
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    def execute(self) -> None:
        job = self.current_job()
        if not job.source_path or not job.destination_path:
            QMessageBox.warning(self, "Missing sync paths", "Choose both local and remote paths before executing.")
            return
        if self.remote_ops is None or self.transfer_manager is None:
            QMessageBox.information(self, "Sync unavailable", "Connect to an SSH/SFTP server before executing sync.")
            return
        self._set_busy(True, "Rebuilding sync preview before execution...")
        worker = AsyncWorker(lambda: self._build_preview(job))
        self._workers.append(worker)
        worker.succeeded.connect(lambda result: self._confirm_and_execute(job, result))
        worker.failed.connect(self._show_error)
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    def current_job(self) -> SyncJob:
        selected = self.saved_jobs.currentData(USER_ROLE_JOB)
        job_id = getattr(selected, "id", None)
        mode = self.mode.currentData(USER_ROLE_JOB)
        local_path = self.local_path.text().strip()
        remote_path = self.remote_path.text().strip()
        return SyncJob(
            id=job_id or str(uuid4()),
            name=self.job_name.text().strip() or "Untitled sync preview",
            mode=mode,
            source_path=remote_path if mode == SyncMode.REMOTE_TO_LOCAL else local_path,
            destination_path=local_path if mode == SyncMode.REMOTE_TO_LOCAL else remote_path,
            ignore_patterns=self._ignore_patterns(),
            profile_id=self.profile_id,
            transfer_engine=str(self.transfer_engine.currentData() or "queue"),
        )

    async def _build_preview(self, job: SyncJob) -> OperationResult:
        local_root = Path(job.source_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.destination_path).expanduser()
        remote_root = job.destination_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.source_path
        if not local_root.exists() or not local_root.is_dir():
            return OperationResult.failure("Local sync path must be an existing folder.")
        local_manifest = await asyncio.to_thread(self._local_manifest, local_root, job.ignore_patterns)
        remote_result = await self._remote_manifest(remote_root, job.ignore_patterns)
        if not remote_result.ok:
            return remote_result
        remote_manifest = remote_result.data
        baseline = None
        if job.mode == SyncMode.TWO_WAY and self.baseline_service is not None:
            baseline = await asyncio.to_thread(self.baseline_service.get, job.id)
        if job.mode == SyncMode.REMOTE_TO_LOCAL:
            preview = self.planner.preview_from_manifests(job, remote_manifest, local_manifest)
        else:
            preview = self.planner.preview_from_manifests(job, local_manifest, remote_manifest, baseline)
        if job.mode == SyncMode.TWO_WAY and preview.conflicts and job.checksum_policy == "ambiguous":
            local_manifest, remote_manifest = await self._add_conflict_checksums(
                local_root,
                remote_root,
                local_manifest,
                remote_manifest,
                preview.conflicts,
            )
            preview = self.planner.preview_from_manifests(job, local_manifest, remote_manifest, baseline)
        return OperationResult.success("Sync preview built.", data=preview)

    def _local_manifest(self, root: Path, ignore_patterns: list[str]) -> list[SyncManifestEntry]:
        entries: list[SyncManifestEntry] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if should_ignore(relative, ignore_patterns):
                continue
            stat = path.stat()
            entries.append(
                SyncManifestEntry(
                    path=relative,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                )
            )
        return entries

    async def _remote_manifest(self, root: str, ignore_patterns: list[str]) -> OperationResult:
        try:
            entries: list[SyncManifestEntry] = []
            await self._collect_remote_files(root or ".", root or ".", ignore_patterns, entries)
            return OperationResult.success("Remote sync manifest built.", data=entries)
        except Exception as exc:
            return OperationResult.failure("Could not build remote sync manifest.", technical_details=f"{type(exc).__name__}: {exc}")

    async def _collect_remote_files(
        self,
        root: str,
        current: str,
        ignore_patterns: list[str],
        entries: list[SyncManifestEntry],
    ) -> None:
        result = await self.remote_ops.list_dir(current)
        if not result.ok:
            raise RuntimeError(result.message)
        for item in result.data or []:
            relative = self._remote_relative(root, item)
            if should_ignore(relative, ignore_patterns):
                continue
            if item.is_dir:
                await self._collect_remote_files(root, item.path, ignore_patterns, entries)
            elif item.is_file:
                entries.append(
                    SyncManifestEntry(
                        path=relative,
                        size=item.size,
                        modified_at=item.modified_at,
                    )
                )

    def _remote_relative(self, root: str, item: FileItem) -> str:
        normalized_root = root.strip("/") if root not in {"", "."} else ""
        item_path = item.path.strip("/")
        if not normalized_root:
            return item_path
        return posixpath.relpath(item_path, normalized_root)

    def _show_preview(self, result: OperationResult) -> None:
        preview: SyncPreview = result.data
        self.model.set_preview(preview)
        self.status.setText(
            " | ".join(
                [
                    f"Upload {len(preview.uploads)}",
                    f"Download {len(preview.downloads)}",
                    f"Overwrite {len(preview.overwrites)}",
                    f"Delete {len(preview.deletes)}",
                    f"Conflict {len(preview.conflicts)}",
                    f"Skip {len(preview.skipped)}",
                    f"Size {human_size(preview.total_size)}",
                ]
            )
        )
        self.log_requested.emit("Sync preview built.", "info")

    def _show_error(self, result: OperationResult) -> None:
        self.status.setText(result.message)
        self.log_requested.emit(result.message, "error")
        if result.technical_details:
            self.log_requested.emit(result.technical_details, "error")
        QMessageBox.warning(self, "Sync preview failed", result.message)

    def _finish_worker(self, worker: AsyncWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if not self._workers:
            self._set_busy(False)

    def _confirm_and_execute(self, job: SyncJob, result: OperationResult) -> None:
        preview: SyncPreview = result.data
        self.model.set_preview(preview)
        if preview.conflicts:
            conflict_entries = [entry for entry in preview.entries if entry.action == SyncAction.CONFLICT]
            dialog = SyncConflictDialog(
                conflict_entries,
                compare_callback=lambda path: self._compare_conflict(job, path),
                parent=self,
            )
            if dialog.exec() != SyncConflictDialog.DialogCode.Accepted:
                self.status.setText("Sync execution cancelled with unresolved conflicts.")
                return
            preview = self.conflict_resolver.resolve(
                preview,
                dialog.decisions(),
                suffix=job.conflict_suffix,
            ).preview
            self.model.set_preview(preview)
        if not self._confirm_execution(preview):
            self.status.setText("Sync execution cancelled.")
            return
        self._set_busy(True, "Executing sync plan...")
        self.execution_started.emit()
        if job.transfer_engine == "rsync" and job.mode != SyncMode.TWO_WAY:
            factory = lambda: self._execute_rsync_and_capture_baseline(job, preview)
        else:
            factory = lambda: self._execute_and_capture_baseline(job, preview)
        worker = AsyncWorker(factory)
        self._workers.append(worker)
        worker.succeeded.connect(self._show_execution_result)
        worker.failed.connect(self._show_error)
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    def _confirm_execution(self, preview: SyncPreview) -> bool:
        destructive_downloads = self._destructive_download_count(preview)
        destructive_count = len(preview.overwrites) + len(preview.deletes) + destructive_downloads
        if destructive_count:
            message = (
                "This sync will make destructive changes.\n\n"
                f"Uploads: {len(preview.uploads)}\n"
                f"Downloads: {len(preview.downloads)}\n"
                f"Overwrites: {len(preview.overwrites) + destructive_downloads}\n"
                f"Deletes: {len(preview.deletes)}\n\n"
                "No automatic backup will be created in this phase."
            )
        else:
            message = (
                "Queue this sync plan?\n\n"
                f"Uploads: {len(preview.uploads)}\n"
                f"Downloads: {len(preview.downloads)}"
            )
        response = QMessageBox.question(self, "Execute sync", message)
        return response == QMessageBox.StandardButton.Yes

    def _destructive_download_count(self, preview: SyncPreview) -> int:
        return len(
            [
                entry
                for entry in preview.entries
                if entry.action == SyncAction.DOWNLOAD and entry.destination_size is not None
            ]
        )

    def _show_execution_result(self, result: OperationResult) -> None:
        data: SyncExecutionResult = result.data
        for message in result.logs:
            self.log_requested.emit(message, "info")
        self.status.setText(
            " | ".join(
                [
                    f"Queued transfers {data.queued_transfers}",
                    f"Local deletes {data.local_deletes}",
                    f"Remote deletes {data.remote_deletes}",
                    f"Skipped {data.skipped}",
                ]
            )
        )
        self.log_requested.emit(result.message, "info")
        self.execution_finished.emit(result)

    async def _execute_and_capture_baseline(self, job: SyncJob, preview: SyncPreview) -> OperationResult:
        result = await self.executor.execute(
            job,
            preview,
            self.remote_ops,
            self.transfer_manager,
            policy=SyncExecutionPolicy(destructive_confirmed=True),
        )
        return await self._capture_baseline(job, preview, result)

    async def _execute_rsync_and_capture_baseline(self, job: SyncJob, preview: SyncPreview) -> OperationResult:
        if self.connection is None or self.rsync_adapter is None:
            return OperationResult.failure("rsync acceleration is not available for this connection.")
        local_root = Path(job.source_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.destination_path).expanduser()
        remote_root = job.destination_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.source_path
        direction = (
            RsyncDirection.REMOTE_TO_LOCAL
            if job.mode == SyncMode.REMOTE_TO_LOCAL
            else RsyncDirection.LOCAL_TO_REMOTE
        )
        transfer_direction = (
            TransferDirection.SERVER_TO_LOCAL
            if job.mode == SyncMode.REMOTE_TO_LOCAL
            else TransferDirection.LOCAL_TO_SERVER
        )
        job_record = TransferJob(
            source_connection=self.profile_id if direction == RsyncDirection.REMOTE_TO_LOCAL else None,
            destination_connection=self.profile_id if direction == RsyncDirection.LOCAL_TO_REMOTE else None,
            source_path=remote_root if direction == RsyncDirection.REMOTE_TO_LOCAL else str(local_root),
            destination_path=str(local_root) if direction == RsyncDirection.REMOTE_TO_LOCAL else remote_root,
            direction=transfer_direction,
            size=preview.total_size,
            bytes_total=preview.total_size,
        )
        self.transfer_manager.add_external_job(job_record)
        self.transfer_manager.register_external_task(job_record, asyncio.current_task())

        def progress(percent: float) -> None:
            total = max(preview.total_size, 1)
            job_record.update_progress(
                bytes_done=int(total * percent / 100),
                bytes_total=total,
                current_file="rsync",
            )
            self.transfer_manager.notify_external_job(job_record)

        local_value = str(local_root).rstrip("/") + "/"
        remote_value = remote_root.rstrip("/") + "/"
        try:
            result = await self.rsync_adapter.run_profile_transfer(
                profile=self.connection.profile,
                local_path=local_value,
                remote_path=remote_value,
                direction=direction,
                delete=bool(preview.deletes),
                destructive_confirmed=True,
                exclude_patterns=job.ignore_patterns,
                progress_callback=progress,
            )
            if not result.ok:
                job_record.mark_failed(result.message)
                return result
            job_record.mark_completed()
            result.data = SyncExecutionResult(
                queued_transfers=1,
                local_deletes=len(preview.deletes) if job.mode == SyncMode.REMOTE_TO_LOCAL else 0,
                remote_deletes=len(preview.deletes) if job.mode == SyncMode.LOCAL_TO_REMOTE else 0,
                skipped=len(preview.skipped),
            )
            result.logs.append("One-way sync executed with rsync acceleration.")
            return await self._capture_baseline(job, preview, result)
        except asyncio.CancelledError:
            job_record.mark_cancelled()
            raise
        finally:
            self.transfer_manager.finish_external_job(job_record)

    async def _capture_baseline(
        self,
        job: SyncJob,
        preview: SyncPreview,
        result: OperationResult,
    ) -> OperationResult:
        if not result.ok or self.baseline_service is None:
            return result
        local_root = Path(job.source_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.destination_path).expanduser()
        remote_root = job.destination_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.source_path
        local_manifest = await asyncio.to_thread(self._local_manifest, local_root, job.ignore_patterns)
        remote_result = await self._remote_manifest(remote_root, job.ignore_patterns)
        if not remote_result.ok:
            return OperationResult.failure(
                "Sync completed, but the new baseline could not be verified.",
                technical_details=remote_result.technical_details,
                warnings=["The previous baseline was preserved."],
            )
        await asyncio.to_thread(
            self.baseline_service.save,
            job=job,
            local_entries=local_manifest,
            remote_entries=remote_result.data,
            preserve_paths={
                entry.path
                for entry in preview.entries
                if entry.action == SyncAction.SKIP and entry.reason.startswith("Conflict skipped")
            },
        )
        result.logs.append("Sync baseline updated after successful verification.")
        return result

    async def _add_conflict_checksums(
        self,
        local_root: Path,
        remote_root: str,
        local_entries: list[SyncManifestEntry],
        remote_entries: list[SyncManifestEntry],
        conflict_paths: list[str],
    ) -> tuple[list[SyncManifestEntry], list[SyncManifestEntry]]:
        conflicts = set(conflict_paths)
        local_updated: list[SyncManifestEntry] = []
        remote_updated: list[SyncManifestEntry] = []
        for entry in local_entries:
            if entry.path in conflicts:
                checksum = await asyncio.to_thread(self._local_checksum, local_root / entry.path)
                entry = replace(entry, checksum=checksum)
            local_updated.append(entry)
        for entry in remote_entries:
            if entry.path in conflicts and hasattr(self.remote_ops, "calculate_checksum"):
                result = await self.remote_ops.calculate_checksum(posixpath.join(remote_root, entry.path))
                if result.ok:
                    entry = replace(entry, checksum=result.data)
            remote_updated.append(entry)
        return local_updated, remote_updated

    def _local_checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(256 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _compare_conflict(self, job: SyncJob, relative_path: str) -> None:
        worker = AsyncWorker(lambda: self._load_conflict_text(job, relative_path))
        self._workers.append(worker)
        worker.succeeded.connect(
            lambda result: DiffViewerDialog(
                result.data[0],
                result.data[1],
                title=f"Sync conflict: {relative_path}",
                parent=self,
            ).exec()
        )
        worker.failed.connect(self._show_error)
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    async def _load_conflict_text(self, job: SyncJob, relative_path: str) -> OperationResult:
        local_root = Path(job.source_path).expanduser()
        remote_root = job.destination_path
        local_path = local_root / relative_path
        if not local_path.exists() or local_path.stat().st_size > 2 * 1024 * 1024 or is_probably_binary(local_path):
            return OperationResult.failure("Visual diff is available only for text files up to 2 MiB.")
        with tempfile.TemporaryDirectory(prefix="rfm-sync-diff-") as folder:
            remote_temp = Path(folder) / Path(relative_path).name
            download = await self.remote_ops.download_file(posixpath.join(remote_root, relative_path), remote_temp)
            if not download.ok:
                return download
            if remote_temp.stat().st_size > 2 * 1024 * 1024 or is_probably_binary(remote_temp):
                return OperationResult.failure("Visual diff is available only for text files up to 2 MiB.")
            local_encoding = detect_encoding(local_path)
            remote_encoding = detect_encoding(remote_temp)
            return OperationResult.success(
                "Conflict text loaded.",
                data=(
                    local_path.read_text(encoding=local_encoding),
                    remote_temp.read_text(encoding=remote_encoding),
                ),
            )

    def _save_current_job(self) -> None:
        job = self.current_job()
        self.save_requested.emit(job)

    def _delete_selected_job(self) -> None:
        job_id = self._selected_job_id()
        if job_id:
            self.delete_requested.emit(job_id)

    def _load_selected_job(self) -> None:
        job = self.saved_jobs.currentData(USER_ROLE_JOB)
        if not isinstance(job, SyncJob):
            self.job_name.clear()
            return
        self.job_name.setText(job.name)
        self.local_path.setText(job.source_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.destination_path)
        self.remote_path.setText(job.destination_path if job.mode != SyncMode.REMOTE_TO_LOCAL else job.source_path)
        self.ignore_patterns.setPlainText(", ".join(job.ignore_patterns or DEFAULT_IGNORE_PATTERNS))
        for index in range(self.mode.count()):
            if self.mode.itemData(index, USER_ROLE_JOB) == job.mode:
                self.mode.setCurrentIndex(index)
                break
        engine_index = self.transfer_engine.findData(job.transfer_engine)
        self.transfer_engine.setCurrentIndex(engine_index if engine_index >= 0 else 0)
        self._sync_engine_enabled()

    def _selected_job_id(self) -> str | None:
        job = self.saved_jobs.currentData(USER_ROLE_JOB)
        return getattr(job, "id", None)

    def _ignore_patterns(self) -> list[str]:
        text = self.ignore_patterns.toPlainText()
        parts = [part.strip() for chunk in text.splitlines() for part in chunk.split(",")]
        return [part for part in parts if part]

    def _browse_local(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose local sync folder", self.local_path.text())
        if path:
            self.local_path.setText(path)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.preview_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy)
        self._sync_execute_enabled(not busy)
        if message:
            self.status.setText(message)

    def _sync_execute_enabled(self, available: bool = True) -> None:
        self.execute_button.setEnabled(bool(available and self.remote_ops is not None and self.transfer_manager is not None))

    def _sync_engine_enabled(self, *_args) -> None:  # type: ignore[no-untyped-def]
        supports_rsync = bool(
            self.connection
            and self.connection.capabilities.can_exec_command
            and self.connection.profile.auth_type.value in {"ssh_key", "ssh_agent"}
            and self.mode.currentData(USER_ROLE_JOB) != SyncMode.TWO_WAY
        )
        model = self.transfer_engine.model()
        item = model.item(1) if hasattr(model, "item") else None
        if item is not None:
            item.setEnabled(supports_rsync)
        if not supports_rsync and self.transfer_engine.currentData() == "rsync":
            self.transfer_engine.setCurrentIndex(0)

    def _saved_job_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("Saved job"))
        layout.addWidget(self.saved_jobs, 1)
        layout.addWidget(self.delete_button)
        return layout

    def _form_layout(self) -> QGridLayout:
        layout = QGridLayout()
        layout.addWidget(QLabel("Name"), 0, 0)
        layout.addWidget(self.job_name, 0, 1)
        layout.addWidget(QLabel("Mode"), 0, 2)
        layout.addWidget(self.mode, 0, 3)
        layout.addWidget(QLabel("Engine"), 0, 4)
        layout.addWidget(self.transfer_engine, 0, 5)
        layout.addWidget(QLabel("Local folder"), 1, 0)
        layout.addWidget(self.local_path, 1, 1)
        layout.addWidget(self.browse_local, 1, 2)
        layout.addWidget(QLabel("Remote folder"), 1, 3)
        layout.addWidget(self.remote_path, 1, 4)
        layout.addWidget(QLabel("Ignore"), 2, 0)
        layout.addWidget(self.ignore_patterns, 2, 1, 1, 5)
        return layout

    def _action_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)
        self.preview_button.setStyleSheet("QPushButton { background: #18181b; color: #e4e4e7; border: 1px solid #27272a; border-radius: 6px; height: 32px; padding: 0 16px; } QPushButton:hover { background: #27272a; }")
        self.save_button.setStyleSheet("QPushButton { background: #18181b; color: #e4e4e7; border: 1px solid #27272a; border-radius: 6px; height: 32px; padding: 0 14px; } QPushButton:hover { background: #27272a; }")
        self.execute_button.setStyleSheet("QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; border-radius: 6px; height: 32px; padding: 0 20px; } QPushButton:hover { background: #4f46e5; }")

        layout.addWidget(self.preview_button)
        layout.addStretch()
        layout.addWidget(self.execute_button)
        return layout
