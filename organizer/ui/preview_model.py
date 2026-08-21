"""Table model backing the preview screen. Encodes status via row color and
lets the user toggle inclusion per row via a checkbox column."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from ..models import PlanItem, Status

_STATUS_LABELS = {
    Status.READY: "Ready",
    Status.INFERRED: "Inferred",
    Status.DUPLICATE: "Duplicate",
    Status.CONFLICT: "Conflict",
    Status.NEEDS_REVIEW: "Needs Review",
}

_STATUS_COLORS = {
    Status.READY: None,
    Status.INFERRED: QColor(255, 244, 196),
    Status.DUPLICATE: QColor(255, 221, 179),
    Status.CONFLICT: QColor(255, 199, 199),
    Status.NEEDS_REVIEW: QColor(224, 224, 224),
}

COL_INCLUDE = 0
COL_STATUS = 1
COL_CURRENT = 2
COL_NEW = 3
COL_ALBUM_ARTIST = 4
COL_ALBUM = 5
COL_SOURCE = 6
COL_GROUP = 7
COL_NOTES = 8

_HEADERS = [
    "Include",
    "Status",
    "Current Location",
    "New Location",
    "Album Artist",
    "Album",
    "Metadata Source",
    "Group",
    "Notes",
]


class PreviewModel(QAbstractTableModel):
    summary_changed = Signal()

    def __init__(self, items: List[PlanItem] = None, parent=None):
        super().__init__(parent)
        self._items: List[PlanItem] = items or []

    def set_items(self, items: List[PlanItem]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()
        self.summary_changed.emit()

    def items(self) -> List[PlanItem]:
        return self._items

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return _HEADERS[section]

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_INCLUDE:
            item = self._items[index.row()]
            if item.dest_path is None:
                return base  # needs-review rows: not checkable, no valid destination yet
            return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = index.column()

        if role == Qt.CheckStateRole and col == COL_INCLUDE:
            if item.dest_path is None:
                return None
            return Qt.Checked if item.include else Qt.Unchecked

        if role == Qt.BackgroundRole:
            color = _STATUS_COLORS.get(item.status)
            return color

        if role == Qt.ToolTipRole:
            return item.notes or None

        if role == Qt.DisplayRole:
            if col == COL_STATUS:
                return _STATUS_LABELS.get(item.status, item.status.value)
            if col == COL_CURRENT:
                return str(item.source_path)
            if col == COL_NEW:
                return str(item.dest_path) if item.dest_path else "(unresolved)"
            if col == COL_ALBUM_ARTIST:
                return item.track.album_artist or ""
            if col == COL_ALBUM:
                return item.track.album or ""
            if col == COL_SOURCE:
                return item.track.metadata_source.value
            if col == COL_GROUP:
                return item.group_id or ""
            if col == COL_NOTES:
                return item.notes
        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == COL_INCLUDE:
            item = self._items[index.row()]
            item.include = value == Qt.Checked
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.summary_changed.emit()
            return True
        return False

    def set_all_included(self, include: bool, only_status: Status = None) -> None:
        if not self._items:
            return
        top_left = self.index(0, COL_INCLUDE)
        bottom_right = self.index(len(self._items) - 1, COL_INCLUDE)
        for item in self._items:
            if item.dest_path is None:
                continue
            if only_status is not None and item.status != only_status:
                continue
            item.include = include
        self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole])
        self.summary_changed.emit()

    def summary_counts(self) -> dict:
        counts = {s: 0 for s in Status}
        included = 0
        for item in self._items:
            counts[item.status] += 1
            if item.include:
                included += 1
        counts["included"] = included
        counts["total"] = len(self._items)
        return counts
