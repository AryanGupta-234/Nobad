from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from transfers.events import TransferLogEvent
from transfers.transfer_job import TransferJob
from transfers.transfer_manager import TransferManager


class QtTransferSignals(QObject):
    """Re-emits the Qt-free TransferManager events as Qt signals.

    The manager's events fire on the asyncio runtime thread. This object lives on the GUI thread, so slots of GUI
    objects connected here are queued onto the GUI thread (the same delivery the manager's old Qt signals had)."""

    job_updated = Signal(object)
    log_event = Signal(object)
    batch_finished = Signal(str)

    def __init__(self, manager: TransferManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        manager.job_updated.connect(self._on_job_updated)
        manager.log_event.connect(self._on_log_event)
        manager.batch_finished.connect(self._on_batch_finished)

    def detach(self) -> None:
        self._manager.job_updated.disconnect(self._on_job_updated)
        self._manager.log_event.disconnect(self._on_log_event)
        self._manager.batch_finished.disconnect(self._on_batch_finished)

    def _on_job_updated(self, job: TransferJob) -> None:
        self.job_updated.emit(job)

    def _on_log_event(self, event: TransferLogEvent) -> None:
        self.log_event.emit(event)

    def _on_batch_finished(self, batch_id: str) -> None:
        self.batch_finished.emit(batch_id)
