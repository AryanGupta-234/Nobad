from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHeaderView, QStyle, QTableView, QTreeWidget, QTreeWidgetItem

from file_ops.base import FileItem, FileKind, human_size
from ui.icons import get_icon
from ui.item_delegates import FileTableItemDelegate


def format_modified_at(val: object) -> str:
    if not val:
        return ""
    if isinstance(val, (int, float)):
        from datetime import datetime
        return datetime.fromtimestamp(val).strftime("%Y-%m-%d %H:%M")
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M")  # type: ignore[union-attr]
    return str(val)[:16]


def get_file_item_icon(item: FileItem) -> QIcon:
    if item.is_dir:
        return get_icon("folder", color="#f59e0b", size=18)
    if item.kind == FileKind.SYMLINK:
        return get_icon("connections", color="#38bdf8", size=18)
    name_lower = item.name.lower()
    if "." in name_lower:
        ext = name_lower.split(".")[-1]
        if ext in {"py", "js", "ts", "jsx", "tsx", "html", "css", "json", "yaml", "yml", "toml", "sh", "sql", "md"}:
            return get_icon("code", color="#818cf8", size=18)
        if ext in {"zip", "tar", "gz", "bz2", "xz", "7z", "rar"}:
            return get_icon("archive", color="#c084fc", size=18)
        if ext in {"key", "pem", "pub", "crt", "cert"}:
            return get_icon("credentials", color="#fb7185", size=18)
    return get_icon("file", color="#a1a1aa", size=18)


class FileTableModel(QAbstractTableModel):
    HEADERS = ["Name", "Size", "Type", "Modified", "Permissions", "Owner", "Group"]

    def __init__(self) -> None:
        super().__init__()
        self.all_items: list[FileItem] = []
        self.items: list[FileItem] = []
        self.filter_text = ""
        self._icons = {
            FileKind.DIRECTORY: self._standard_icon(QStyle.StandardPixmap.SP_DirIcon),
            FileKind.SYMLINK: self._standard_icon(QStyle.StandardPixmap.SP_FileLinkIcon),
            FileKind.FILE: self._standard_icon(QStyle.StandardPixmap.SP_FileIcon),
            FileKind.OTHER: self._standard_icon(QStyle.StandardPixmap.SP_FileIcon),
        }

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.items)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return item
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return get_file_item_icon(item)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        values = [
            item.name,
            human_size(item.size),
            item.kind.value,
            format_modified_at(item.modified_at),
            item.permissions or "",
            item.owner or "",
            item.group or "",
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def set_items(self, items: list[FileItem]) -> None:
        self.beginResetModel()
        self.all_items = list(items)
        self.items = self._filtered_items()
        self.endResetModel()

    def set_filter(self, text: str) -> None:
        self.beginResetModel()
        self.filter_text = text.strip().lower()
        self.items = self._filtered_items()
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        reverse = order == Qt.SortOrder.DescendingOrder

        def key(item: FileItem):
            values = [
                item.name.lower(),
                item.size or 0,
                item.kind.value,
                item.modified_at or "",
                item.permissions or "",
                item.owner or "",
                item.group or "",
            ]
            return values[column]

        self.layoutAboutToBeChanged.emit()
        self.items.sort(key=key, reverse=reverse)
        self.layoutChanged.emit()

    def _standard_icon(self, pixmap: QStyle.StandardPixmap) -> QIcon:
        style = QApplication.style()
        if style is None:
            return QIcon()
        return style.standardIcon(pixmap)

    def _filtered_items(self) -> list[FileItem]:
        if not self.filter_text:
            return list(self.all_items)
        return [item for item in self.all_items if self.filter_text in item.name.lower()]


class FileTableWidget(QTableView):
    file_activated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.file_model = FileTableModel()
        self.setModel(self.file_model)
        self.setItemDelegate(FileTableItemDelegate(self))
        self.setShowGrid(False)
        self.verticalHeader().setDefaultSectionSize(32)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().resizeSection(1, 85)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().resizeSection(3, 140)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().resizeSection(4, 95)
        self.setColumnHidden(2, True)  # Type (already conveyed via icon)
        self.setColumnHidden(5, True)  # Owner
        self.setColumnHidden(6, True)  # Group
        self.doubleClicked.connect(self._activated)

    def set_items(self, items: list[FileItem]) -> None:
        self.file_model.set_items(items)

    def set_filter(self, text: str) -> None:
        self.file_model.set_filter(text)

    def selected_items_data(self) -> list[FileItem]:
        rows = {index.row() for index in self.selectionModel().selectedRows()}
        return [self.file_model.items[row] for row in sorted(rows) if row < len(self.file_model.items)]

    def _activated(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        item = self.file_model.items[index.row()]
        self.file_activated.emit(item)


class FileTreeWidget(QTreeWidget):
    """A lazy, expandable tree representation of ``FileItem`` values."""

    file_activated = Signal(object)
    folder_expanded = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(FileTableModel.HEADERS)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.setIndentation(18)
        self.setRootIsDecorated(True)
        self.setAnimated(True)

        header = self.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 85)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, 140)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 95)
        self.setColumnHidden(2, True)  # Type hidden (icon shows it)
        self.setColumnHidden(5, True)  # Owner hidden
        self.setColumnHidden(6, True)  # Group hidden

        self._all_items: list[FileItem] = []
        self.itemDoubleClicked.connect(self._activated)
        self.itemExpanded.connect(self._expanded)

    def set_items(self, items: list[FileItem]) -> None:
        self._all_items = list(items)
        self._populate(self._all_items)

    def set_filter(self, text: str) -> None:
        needle = text.strip().lower()
        self._populate([item for item in self._all_items if not needle or needle in item.name.lower()])

    def set_children(self, parent: QTreeWidgetItem, items: list[FileItem]) -> None:
        parent.takeChildren()
        for item in items:
            parent.addChild(self._item(item))

    def selected_items_data(self) -> list[FileItem]:
        return [item.data(0, Qt.ItemDataRole.UserRole) for item in self.selectedItems() if isinstance(item.data(0, Qt.ItemDataRole.UserRole), FileItem)]

    def _populate(self, items: list[FileItem]) -> None:
        self.clear()
        for item in items:
            self.addTopLevelItem(self._item(item))

    def _item(self, item: FileItem) -> QTreeWidgetItem:
        values = [
            item.name,
            human_size(item.size),
            item.kind.value,
            format_modified_at(item.modified_at),
            item.permissions or "",
            item.owner or "",
            item.group or "",
        ]
        node = QTreeWidgetItem(values)
        node.setData(0, Qt.ItemDataRole.UserRole, item)
        node.setIcon(0, get_file_item_icon(item))
        if item.is_dir:
            loading = QTreeWidgetItem(["Loading…"])
            loading.setForeground(0, QColor("#71717a"))
            node.addChild(loading)
        return node

    def _activated(self, node: QTreeWidgetItem, _column: int) -> None:
        item = node.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(item, FileItem):
            self.file_activated.emit(item)

    def _expanded(self, node: QTreeWidgetItem) -> None:
        item = node.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(item, FileItem) and item.is_dir and node.childCount() == 1 and node.child(0).data(0, Qt.ItemDataRole.UserRole) is None:
            self.folder_expanded.emit(item, node)
