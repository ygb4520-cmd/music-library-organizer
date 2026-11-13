"""Preview screen widget: filterable table of every planned move, a summary
bar, and bulk selection helpers. Row color (set on the model) is the main
visual signal for clean vs inferred vs duplicate/conflict vs needs-review."""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..models import Status
from .preview_model import COL_ALBUM, COL_ALBUM_ARTIST, COL_CURRENT, COL_INCLUDE, COL_NEW, PreviewModel


_ALL = "__all__"


class _FilterProxy(QSortFilterProxyModel):
    """Text search (all columns) combined with a status and an artist filter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status_filter = None  # Status or None
        self.artist_filter = None  # artist name or None

    def set_status_filter(self, status) -> None:
        self.status_filter = status
        self.invalidateFilter()

    def set_artist_filter(self, artist) -> None:
        self.artist_filter = artist
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent) -> bool:
        if not super().filterAcceptsRow(row, parent):
            return False
        item = self.sourceModel().items()[row]
        if self.status_filter is not None and item.status != self.status_filter:
            return False
        if self.artist_filter is not None and artist_of(item) != self.artist_filter:
            return False
        return True


def artist_of(item) -> str:
    return (item.track.album_artist or item.track.artist or "").strip()


class PreviewView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.model = PreviewModel()
        self.proxy = _FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # search across all columns

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by path, artist, or album...")
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)

        self.status_combo = QComboBox()
        self.status_combo.addItem("All statuses", None)
        self.status_combo.addItem("Needs manual review", Status.NEEDS_REVIEW)
        self.status_combo.addItem("Duplicates", Status.DUPLICATE)
        self.status_combo.addItem("Path conflicts", Status.CONFLICT)
        self.status_combo.addItem("Inferred", Status.INFERRED)
        self.status_combo.addItem("Ready", Status.READY)
        self.status_combo.currentIndexChanged.connect(
            lambda _i: self.proxy.set_status_filter(self.status_combo.currentData())
        )

        self.artist_combo = QComboBox()
        self.artist_combo.setMinimumWidth(180)
        self.artist_combo.currentIndexChanged.connect(
            lambda _i: self.proxy.set_artist_filter(self.artist_combo.currentData())
        )

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(COL_CURRENT, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_NEW, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_ALBUM_ARTIST, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_ALBUM, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(COL_INCLUDE, 60)
        self.table.verticalHeader().setVisible(False)

        select_all_ready_btn = QPushButton("Select All Ready/Inferred")
        select_all_ready_btn.clicked.connect(self._select_all_safe)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self.model.set_all_included(False))

        top_row = QHBoxLayout()
        top_row.addWidget(self.filter_edit, 1)
        top_row.addWidget(self.status_combo)
        top_row.addWidget(self.artist_combo)
        top_row.addWidget(select_all_ready_btn)
        top_row.addWidget(deselect_all_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addLayout(top_row)
        layout.addWidget(self.table, 1)

        self.model.summary_changed.connect(self._refresh_summary)

    def _select_all_safe(self):
        self.model.set_all_included(True, only_status=Status.READY)
        self.model.set_all_included(True, only_status=Status.INFERRED)

    def set_items(self, items) -> None:
        self.model.set_items(items)
        self._refresh_artists()
        self._refresh_summary()

    def _refresh_artists(self) -> None:
        """Rebuild the artist dropdown from the current items, keeping the
        selection if that artist is still present."""
        previous = self.artist_combo.currentData()
        artists = sorted({artist_of(i) for i in self.model.items()} - {""}, key=str.lower)
        self.artist_combo.blockSignals(True)
        self.artist_combo.clear()
        self.artist_combo.addItem("All artists", None)
        for a in artists:
            self.artist_combo.addItem(a, a)
        idx = self.artist_combo.findData(previous) if previous else 0
        self.artist_combo.setCurrentIndex(max(idx, 0))
        self.artist_combo.blockSignals(False)
        self.proxy.set_artist_filter(self.artist_combo.currentData())

    def remove_items(self, items) -> None:
        self.model.remove_items(items)
        self._refresh_artists()

    def _refresh_summary(self) -> None:
        c = self.model.summary_counts()
        self.summary_label.setText(
            f"<b>{c['total']}</b> files scanned &nbsp;|&nbsp; "
            f"<b>{c['included']}</b> selected to move &nbsp;|&nbsp; "
            f"{c[Status.READY]} ready &middot; "
            f"{c[Status.INFERRED]} inferred &middot; "
            f"{c[Status.DUPLICATE]} duplicates &middot; "
            f"{c[Status.CONFLICT]} path conflicts &middot; "
            f"{c[Status.NEEDS_REVIEW]} need manual review"
        )
