from __future__ import annotations

from file_ops.base import FileItem, FileKind
from ui.file_browser import FileTableModel


def test_file_table_filter_keeps_full_item_list() -> None:
    model = FileTableModel()
    model.set_items(
        [
            FileItem("index.html", "index.html", FileKind.FILE),
            FileItem("app.js", "app.js", FileKind.FILE),
        ]
    )

    model.set_filter("index")

    assert [item.name for item in model.items] == ["index.html"]
    assert [item.name for item in model.all_items] == ["index.html", "app.js"]

    model.set_filter("")

    assert [item.name for item in model.items] == ["index.html", "app.js"]
