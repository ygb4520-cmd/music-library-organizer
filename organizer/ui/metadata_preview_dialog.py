"""Preview + confirm dialog for the metadata-lookup feature. Shows every
proposed MusicBrainz match with a checkbox, and does not write a single tag
until the user clicks "Write Selected Tags" -- mirrors the existing
move-preview philosophy (nothing changes until you explicitly confirm)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
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

from .. import tag_writer
from ..metadata_lookup import MatchCandidate
from ..models import TrackInfo

COL_INCLUDE = 0
COL_FILE = 1
COL_CURRENT = 2
COL_MATCH = 3
COL_CONFIDENCE = 4


class MetadataPreviewDialog(QDialog):
    def __init__(self, results: List[Tuple[TrackInfo, Optional[MatchCandidate]]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadata Lookup Results")
        self.resize(900, 500)

        self._rows: List[Tuple[TrackInfo, MatchCandidate]] = [
            (track, match) for track, match in results if match is not None
        ]
        no_match_count = len(results) - len(self._rows)

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"<b>{len(self._rows)}</b> match(es) found "
            f"&middot; <b>{no_match_count}</b> file(s) had no confident match."
        )
        layout.addWidget(summary)

        self.table = QTableWidget(len(self._rows), 5)
        self.table.setHorizontalHeaderLabels(["", "File", "Current Tags", "Suggested Match", "Confidence"])
        self.table.horizontalHeader().setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_MATCH, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_INCLUDE, 30)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        for row, (track, match) in enumerate(self._rows):
            include_item = QTableWidgetItem()
            include_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            # Only pre-check confident matches -- low-confidence ones need a
            # deliberate opt-in, not an easy-to-miss default.
            include_item.setCheckState(Qt.Checked if match.is_confident else Qt.Unchecked)
            self.table.setItem(row, COL_INCLUDE, include_item)

            self.table.setItem(row, COL_FILE, QTableWidgetItem(track.filename))

            current = track.artist or track.title or "(none)"
            self.table.setItem(row, COL_CURRENT, QTableWidgetItem(current))

            match_text = f"{match.artist} — {match.title}"
            if match.album:
                match_text += f" ({match.album})"
            self.table.setItem(row, COL_MATCH, QTableWidgetItem(match_text))

            confidence_item = QTableWidgetItem(f"{match.score}%")
            if not match.is_confident:
                confidence_item.setForeground(Qt.darkYellow)
            self.table.setItem(row, COL_CONFIDENCE, confidence_item)

        layout.addWidget(self.table, 1)

        note = QLabel(
            "This writes ARTIST, TITLE, and ALBUM tags directly to the checked files — "
            "the only place in this app that modifies tags, and only for rows you've checked."
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

    def _write_selected(self):
        selected = [
            (track, match)
            for row, (track, match) in enumerate(self._rows)
            if self.table.item(row, COL_INCLUDE).checkState() == Qt.Checked
        ]
        if not selected:
            QMessageBox.information(self, "Nothing Selected", "No rows are checked.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Tag Write",
            f"Write tags to {len(selected)} file(s)? This modifies the files directly and "
            "cannot be automatically undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        errors = []
        written = 0
        for track, match in selected:
            try:
                tag_writer.write_tags(track.path, artist=match.artist, title=match.title, album=match.album)
                written += 1
            except tag_writer.TagWriteError as e:
                errors.append(f"{track.filename}: {e}")

        summary_lines = [f"Wrote tags to {written} file(s)."]
        if errors:
            summary_lines.append(f"\n{len(errors)} failed:")
            summary_lines.extend(f"  {e}" for e in errors[:20])
        QMessageBox.information(self, "Tag Write Complete", "\n".join(summary_lines))
        self.accept()
