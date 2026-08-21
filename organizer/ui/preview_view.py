"""Preview screen widget: filterable table of every planned move, a summary
bar, and bulk selection helpers. Row color (set on the model) is the main
visual signal for clean vs inferred vs duplicate/conflict vs needs-review."""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
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


class PreviewView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.model = PreviewModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # search across all columns

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by path, artist, or album...")
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)

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
        self._refresh_summary()

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
