from __future__ import annotations

from transfers.transfer_job import TransferDirection, TransferJob
from ui.transfer_queue import TransferTableModel


def test_transfer_table_model_can_update_progress_columns_only() -> None:
    model = TransferTableModel()
    job = TransferJob(None, None, "source", "dest", TransferDirection.LOCAL_TO_SERVER)
    model.update_job(job)
    changed_ranges = []
    model.dataChanged.connect(
        lambda top_left, bottom_right, _roles: changed_ranges.append((top_left.column(), bottom_right.column()))
    )

    job.mark_running()
    job.update_progress(bytes_done=50, bytes_total=100, current_file="source")
    model.update_job(job, columns=TransferTableModel.PROGRESS_COLUMNS)

    assert changed_ranges == [
        (TransferTableModel.CURRENT_FILE_COLUMN, TransferTableModel.ETA_COLUMN),
    ]
