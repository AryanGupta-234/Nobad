from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionProgressBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from transfers.transfer_job import TransferJob, TransferStatus
from ui.icons import get_icon
from ui.theme import DEFAULT_THEME, get_mono_font


class TransferTableModel(QAbstractTableModel):
    HEADERS = ["Source", "Destination", "Direction", "Current File", "Progress", "Bytes", "Speed", "ETA", "Retries", "Status"]
    CURRENT_FILE_COLUMN = 3
    PROGRESS_COLUMN = 4
    BYTES_COLUMN = 5
    SPEED_COLUMN = 6
    ETA_COLUMN = 7
    PROGRESS_COLUMNS = (CURRENT_FILE_COLUMN, PROGRESS_COLUMN, BYTES_COLUMN, SPEED_COLUMN, ETA_COLUMN)

    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[TransferJob] = []
        self._rows_by_id: dict[str, int] = {}

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.jobs)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.jobs):
            return None
        job = self.jobs[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return job
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        values = [
            job.source_path,
            job.destination_path,
            job.direction.value,
            job.current_file or "",
            f"{job.progress:.0f}%",
            self._bytes_label(job),
            self._speed_label(job.speed),
            self._eta_label(job.eta_seconds),
            str(job.retry_count),
            job.status.value if not job.error_message else f"{job.status.value}: {job.error_message}",
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def update_job(self, job: TransferJob, *, columns: tuple[int, ...] | None = None) -> None:
        row = self._rows_by_id.get(job.id)
        if row is None:
            self.beginInsertRows(QModelIndex(), len(self.jobs), len(self.jobs))
            self._rows_by_id[job.id] = len(self.jobs)
            self.jobs.append(job)
            self.endInsertRows()
            return
        self.jobs[row] = job
        changed_columns = columns or tuple(range(self.columnCount()))
        top_left = self.index(row, min(changed_columns))
        bottom_right = self.index(row, max(changed_columns))
        self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole])

    def set_jobs(self, jobs: list[TransferJob]) -> None:
        self.beginResetModel()
        self.jobs = list(jobs)
        self._rows_by_id = {job.id: index for index, job in enumerate(self.jobs)}
        self.endResetModel()

    def selected_job_at(self, row: int) -> TransferJob | None:
        if row < 0 or row >= len(self.jobs):
            return None
        return self.jobs[row]

    def job_for_id(self, job_id: str) -> TransferJob | None:
        row = self._rows_by_id.get(job_id)
        if row is None:
            return None
        return self.selected_job_at(row)

    def row_for_job(self, job_id: str) -> int | None:
        return self._rows_by_id.get(job_id)

    def _bytes_label(self, job: TransferJob) -> str:
        if job.bytes_total is None:
            return ""
        return f"{self._human_size(job.bytes_done)} / {self._human_size(job.bytes_total)}"

    def _speed_label(self, speed: float | None) -> str:
        if speed is None:
            return ""
        return f"{self._human_size(int(speed))}/s"

    def _eta_label(self, eta: float | None) -> str:
        if eta is None:
            return ""
        if eta < 60:
            return f"{eta:.0f}s"
        minutes, seconds = divmod(int(eta), 60)
        return f"{minutes}m {seconds}s"

    def _human_size(self, size: int) -> str:
        value = float(size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024 or unit == "TB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"


class ProgressBarDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:  # type: ignore[no-untyped-def]
        job = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(job, TransferJob):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        progress = max(0, min(100, int(round(job.progress))))
        rect = option.rect.adjusted(6, 6, -6, -6)

        # Track background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(DEFAULT_THEME.surface_card))
        painter.drawRoundedRect(rect, 4, 4)

        # Gradient progress fill
        fill_width = int(rect.width() * progress / 100)
        if fill_width > 0:
            fill_rect = QRect(rect.left(), rect.top(), fill_width, rect.height())
            grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
            grad.setColorAt(0, QColor(DEFAULT_THEME.accent))
            grad.setColorAt(1, QColor(DEFAULT_THEME.success))
            painter.setBrush(grad)
            painter.drawRoundedRect(fill_rect, 4, 4)

        # Percentage label
        painter.setFont(get_mono_font(size=10, weight=QFont.Weight.Medium))
        painter.setPen(QColor(DEFAULT_THEME.text))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, f"{progress}%")
        painter.restore()


class TransferQueuePanel(QWidget):
    cancel_requested = Signal(str)
    retry_requested = Signal(str)
    retry_failed_requested = Signal()
    clear_completed_requested = Signal()
    clear_failed_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.model = TransferTableModel()
        self._pending_progress_jobs: dict[str, TransferJob] = {}
        self._last_status_by_id: dict[str, TransferStatus] = {}
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(75)
        self._flush_timer.timeout.connect(self._flush_progress_updates)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(TransferTableModel.PROGRESS_COLUMN, ProgressBarDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.verticalHeader().setVisible(False)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setIcon(get_icon("cancel", size=14))
        self.retry_button = QPushButton("Retry")
        self.retry_button.setIcon(get_icon("sync", size=14))
        self.retry_failed_button = QPushButton("Retry Failed")
        self.retry_failed_button.setIcon(get_icon("sync", size=14))
        self.clear_completed_button = QPushButton("Clear Completed")
        self.clear_completed_button.setIcon(get_icon("cancel", size=14))
        self.clear_failed_button = QPushButton("Clear Failed")
        self.clear_failed_button.setIcon(get_icon("cancel", size=14))

        self.status = QLabel("No transfers queued.")
        self.status.setObjectName("MutedLabel")
        self.bandwidth_label = QLabel("0.0 MB/s")
        self.bandwidth_label.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #10b981; font-weight: 600;")

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 4, 0, 4)
        controls.setSpacing(6)
        for button in [
            self.cancel_button,
            self.retry_button,
            self.retry_failed_button,
            self.clear_completed_button,
            self.clear_failed_button,
        ]:
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(self.bandwidth_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addWidget(self.status)

        self.cancel_button.clicked.connect(self._cancel_selected)
        self.retry_button.clicked.connect(self._retry_selected)
        self.retry_failed_button.clicked.connect(self.retry_failed_requested)
        self.clear_completed_button.clicked.connect(self.clear_completed_requested)
        self.clear_failed_button.clicked.connect(self.clear_failed_requested)
        self._sync_status()

    def add_job(self, job: TransferJob) -> None:
        self.update_job(job)

    def update_job(self, job: TransferJob) -> None:
        if self._should_coalesce_progress(job):
            self._pending_progress_jobs[job.id] = job
            if not self._flush_timer.isActive():
                self._flush_timer.start()
            return

        self._pending_progress_jobs.pop(job.id, None)
        self.model.update_job(job)
        self._last_status_by_id[job.id] = job.status
        self._sync_status()

    def set_jobs(self, jobs: list[TransferJob]) -> None:
        self._pending_progress_jobs.clear()
        self._last_status_by_id = {job.id: job.status for job in jobs}
        self.model.set_jobs(jobs)
        self._sync_status()

    def selected_job(self) -> TransferJob | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.selected_job_at(rows[0].row())

    def _cancel_selected(self) -> None:
        job = self.selected_job()
        if job is not None:
            self.cancel_requested.emit(job.id)

    def _retry_selected(self) -> None:
        job = self.selected_job()
        if job is not None:
            self.retry_requested.emit(job.id)

    def _should_coalesce_progress(self, job: TransferJob) -> bool:
        if self.model.row_for_job(job.id) is None:
            return False
        previous_status = self._last_status_by_id.get(job.id)
        return previous_status == TransferStatus.RUNNING and job.status == TransferStatus.RUNNING

    def _flush_progress_updates(self) -> None:
        if not self._pending_progress_jobs:
            self._flush_timer.stop()
            return
        jobs = list(self._pending_progress_jobs.values())
        self._pending_progress_jobs.clear()
        for job in jobs:
            self.model.update_job(job, columns=TransferTableModel.PROGRESS_COLUMNS)

    def _sync_status(self) -> None:
        jobs = self.model.jobs
        counts = {status: 0 for status in TransferStatus}
        total_speed = sum(job.speed or 0.0 for job in jobs if job.status == TransferStatus.RUNNING)
        if total_speed > 0:
            self.bandwidth_label.setText(f"{self.model._speed_label(total_speed)}")
        else:
            self.bandwidth_label.setText("0.0 B/s")

        for job in jobs:
            counts[job.status] += 1
        if not jobs:
            self.status.setText("No transfers queued.")
            return
        self.status.setText(
            " | ".join(
                [
                    f"Queued {counts[TransferStatus.QUEUED]}",
                    f"Running {counts[TransferStatus.RUNNING]}",
                    f"Done {counts[TransferStatus.COMPLETED]}",
                    f"Failed {counts[TransferStatus.FAILED]}",
                    f"Cancelled {counts[TransferStatus.CANCELLED]}",
                ]
            )
        )
