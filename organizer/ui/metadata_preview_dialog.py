"""Preview + confirm dialog for the metadata-lookup feature. Shows every
proposed MusicBrainz match with a checkbox, sortable/editable fields, and
does not write a single tag until the user clicks "Write Selected Tags" --
mirrors the existing move-preview philosophy (nothing changes until you
explicitly confirm)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import artist_utils, settings, tag_writer
from ..metadata_lookup import MatchCandidate
from ..models import TrackInfo

COL_INCLUDE = 0
COL_FILE = 1
COL_CURRENT = 2
COL_ARTIST = 3
COL_TITLE = 4
COL_ALBUM = 5
COL_SOURCE = 6
COL_MAIN_ONLY = 7
COL_CONFIDENCE = 8

_SOURCE_LABELS = {"filename": "Filename", "fingerprint": "Fingerprint"}


class MetadataPreviewDialog(QDialog):
    def __init__(self, results: List[Tuple[TrackInfo, Optional[MatchCandidate]]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadata Lookup Results")
        self.resize(1000, 500)

        rows = [(track, match) for track, match in results if match is not None]
        no_match_count = len(results) - len(rows)
        rows = self._sorted(rows)
        self._rows: List[Tuple[TrackInfo, MatchCandidate]] = rows

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"<b>{len(self._rows)}</b> match(es) found "
            f"&middot; <b>{no_match_count}</b> file(s) had no confident match. "
            f"Sorted by: {settings.SORT_LABELS[settings.get_sort_order()]} "
            "(click any column header to re-sort)."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        self.table = QTableWidget(len(self._rows), 9)
        self.table.setHorizontalHeaderLabels(
            ["", "File", "Current Tags", "Artist", "Title", "Album", "Found Via", "Main Artist Only", "Confidence"]
        )
        self.table.horizontalHeader().setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_INCLUDE, 30)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)

        default_main_only = settings.get_multi_artist_mode() == settings.MULTI_ARTIST_MAIN_ONLY

        # Bare QTableWidgetItems don't reliably inherit the table's text
        # color on every platform/style (seen on Windows: header text draws
        # fine but every data cell renders blank -- text color ends up
        # matching the cell background). Setting it explicitly on each item
        # avoids depending on that inheritance.
        text_color = self.table.palette().color(QPalette.Active, QPalette.Text)

        for row, (track, match) in enumerate(self._rows):
            include_item = QTableWidgetItem()
            include_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            include_item.setCheckState(Qt.Checked if match.is_confident else Qt.Unchecked)
            self.table.setItem(row, COL_INCLUDE, include_item)

            file_item = QTableWidgetItem(track.filename)
            file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
            file_item.setForeground(text_color)
            self.table.setItem(row, COL_FILE, file_item)

            current = track.artist or track.title or "(none)"
            current_item = QTableWidgetItem(current)
            current_item.setFlags(current_item.flags() & ~Qt.ItemIsEditable)
            current_item.setForeground(text_color)
            self.table.setItem(row, COL_CURRENT, current_item)

            # Editable fields -- pre-filled from the match, but the user can
            # correct anything before writing.
            artist_item = QTableWidgetItem(match.artist)
            artist_item.setForeground(text_color)
            self.table.setItem(row, COL_ARTIST, artist_item)

            title_item = QTableWidgetItem(match.title)
            title_item.setForeground(text_color)
            self.table.setItem(row, COL_TITLE, title_item)

            album_item = QTableWidgetItem(match.album or "")
            album_item.setForeground(text_color)
            self.table.setItem(row, COL_ALBUM, album_item)

            source_item = QTableWidgetItem(_SOURCE_LABELS.get(match.source, match.source))
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
            source_item.setForeground(text_color)
            self.table.setItem(row, COL_SOURCE, source_item)

            has_feat = artist_utils.has_featured_artist(match.artist)
            main_only_item = QTableWidgetItem()
            main_only_item.setForeground(text_color)
            if has_feat:
                main_only_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                main_only_item.setCheckState(Qt.Checked if default_main_only else Qt.Unchecked)
            else:
                # No "feat." credit on this one -- nothing to toggle.
                main_only_item.setFlags(Qt.ItemIsSelectable)
                main_only_item.setText("—")
            self.table.setItem(row, COL_MAIN_ONLY, main_only_item)

            confidence_item = QTableWidgetItem()
            confidence_item.setData(Qt.DisplayRole, match.score)  # numeric sort, not string sort
            confidence_item.setFlags(confidence_item.flags() & ~Qt.ItemIsEditable)
            confidence_item.setForeground(Qt.darkYellow if not match.is_confident else text_color)
            self.table.setItem(row, COL_CONFIDENCE, confidence_item)

        layout.addWidget(self.table, 1)

        note = QLabel(
            "Artist/Title/Album are editable — fix anything before writing. This writes tags "
            "directly to the checked files, the only place in this app that modifies tags."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        button_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        write_btn = QPushButton("Write Selected Tags")
        write_btn.clicked.connect(self._write_selected)
        button_row.addStretch(1)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(write_btn)
        layout.addLayout(button_row)

    def _sorted(
        self, rows: List[Tuple[TrackInfo, MatchCandidate]]
    ) -> List[Tuple[TrackInfo, MatchCandidate]]:
        order = settings.get_sort_order()
        if order == settings.SORT_CONFIDENCE_DESC:
            return sorted(rows, key=lambda r: r[1].score, reverse=True)
        if order == settings.SORT_CONFIDENCE_ASC:
            return sorted(rows, key=lambda r: r[1].score)
        # A-Z: by suggested artist, then title.
        return sorted(rows, key=lambda r: (r[1].artist.lower(), r[1].title.lower()))

    def _write_selected(self):
        to_write = []  # (track, artist, title, album)
        for row, (track, _match) in enumerate(self._rows):
            if self.table.item(row, COL_INCLUDE).checkState() != Qt.Checked:
                continue

            artist = self.table.item(row, COL_ARTIST).text().strip()
            title = self.table.item(row, COL_TITLE).text().strip()
            album = self.table.item(row, COL_ALBUM).text().strip()

            main_only_item = self.table.item(row, COL_MAIN_ONLY)
            if main_only_item.flags() & Qt.ItemIsUserCheckable and main_only_item.checkState() == Qt.Checked:
                artist = artist_utils.main_artist(artist)

            to_write.append((track, artist, title, album))

        if not to_write:
            QMessageBox.information(self, "Nothing Selected", "No rows are checked.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Tag Write",
            f"Write tags to {len(to_write)} file(s)? This modifies the files directly and "
            "cannot be automatically undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        errors = []
        written = 0
        for track, artist, title, album in to_write:
            try:
                tag_writer.write_tags(track.path, artist=artist, title=title, album=album)
                written += 1
            except tag_writer.TagWriteError as e:
                errors.append(f"{track.filename}: {e}")

        summary_lines = [f"Wrote tags to {written} file(s)."]
        if errors:
            summary_lines.append(f"\n{len(errors)} failed:")
            summary_lines.extend(f"  {e}" for e in errors[:20])
        QMessageBox.information(self, "Tag Write Complete", "\n".join(summary_lines))
        self.accept()
