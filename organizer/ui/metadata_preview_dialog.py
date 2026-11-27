"""Preview + confirm dialog for the metadata-lookup feature. Shows every
proposed MusicBrainz match with a checkbox, sortable/editable fields, and
does not write a single tag until the user clicks "Write Selected Tags" --
mirrors the existing move-preview philosophy (nothing changes until you
explicitly confirm)."""
from __future__ import annotations

import html
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import artist_utils, settings, tag_writer
from ..metadata_lookup import LookupResult, LookupStatus, MatchCandidate
from ..metadata_worker import AlternativesWorker
from ..models import TrackInfo
from ..tag_write_worker import TagWriteWorker
from .correction_dialog import CorrectionDialog

COL_INCLUDE = 0
COL_FILE = 1
COL_CURRENT = 2
COL_ARTIST = 3
COL_TITLE = 4
COL_ALBUM = 5
COL_SOURCE = 6
COL_MAIN_ONLY = 7
COL_CONFIDENCE = 8

_SOURCE_LABELS = {"filename": "Filename", "fingerprint": "Fingerprint", "manual": "Manual"}


class MetadataPreviewDialog(QDialog):
    def __init__(
        self,
        results: List[Tuple[TrackInfo, Optional[MatchCandidate]]],
        parent=None,
        reasons: Optional[Dict[object, LookupResult]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Metadata Lookup Results")
        self.resize(1000, 500)

        rows = [(track, match) for track, match in results if match is not None]
        no_match_count = len(results) - len(rows)
        rows = self._sorted(rows)
        self._rows: List[Tuple[TrackInfo, MatchCandidate]] = rows
        self._rejected = {}  # row index -> set of (artist, title) the user marked as wrong
        self._alt_worker = None

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"<b>{len(self._rows)}</b> match(es) found "
            f"&middot; <b>{no_match_count}</b> file(s) had no confident match. "
            f"Sorted by: {settings.SORT_LABELS[settings.get_sort_order()]} "
            "(click any column header to re-sort)."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # Why files got no match (wrong key, fpcalc missing, network down...), so those don't all look like "not in the database".
        reason_text, reason_tip = self._reason_summary(results, reasons or {})
        self.reason_label = QLabel(reason_text)
        self.reason_label.setWordWrap(True)
        self.reason_label.setToolTip(reason_tip)
        self.reason_label.setVisible(bool(reason_text))
        layout.addWidget(self.reason_label)

        self.table = QTableWidget(len(self._rows), 9)
        self.table.setHorizontalHeaderLabels(
            ["", "File", "Current Tags", "Artist", "Title", "Album", "Found Via", "Main Artist Only", "Confidence"]
        )
        self.table.horizontalHeader().setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_INCLUDE, 30)
        # Sorting stays OFF while the rows are filled in and is switched on at the end. With it on, Qt re-sorts the table
        # every time the first cell of a row is set, so the rest of that row's cells land in other rows and most of the
        # table ends up blank.
        self.table.setSortingEnabled(False)
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
            file_item.setData(Qt.UserRole, row)   # index into self._rows, so a re-sorted table still maps to the right file
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

        # Now that every cell is in place, allow click-to-sort. No column is sorted at first (the order from Settings stays).
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self.table, 1)

        note = QLabel(
            "Artist/Title/Album are editable — fix anything before writing. Right-click a row and choose "
            "\"Wrong match\" to try again or enter the tags yourself. This writes tags "
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

    @staticmethod
    def _reason_summary(results, reasons: Dict[object, LookupResult]) -> Tuple[str, str]:
        """(footer text, tooltip) describing why the unmatched files had no match. Empty when nothing is unmatched."""
        groups: Dict[LookupStatus, List[Tuple[str, str]]] = {}
        for track, match in results:
            if match is not None:
                continue
            result = reasons.get(track.path)
            status = result.status if result is not None else LookupStatus.NO_MATCH
            groups.setdefault(status, []).append((track.filename, result.message if result else ""))
        if not groups:
            return "", ""
        # Real problems first, plain "not in the database" last.
        ordered = sorted(groups.items(), key=lambda kv: kv[0] is LookupStatus.NO_MATCH)
        lines = []
        tips = []
        for status, files in ordered:
            sample = files[0][1] or LookupResult([], status).message
            lines.append(f"<b>{len(files)}</b> &times; {html.escape(sample)}")
            tips.append(f"{status.name}:\n  " + "\n  ".join(name for name, _ in files[:15]) + ("\n  ..." if len(files) > 15 else ""))
        return "Why files had no match:<br>" + "<br>".join(lines), "\n\n".join(tips)

    # -- Correcting a wrong match ------------------------------------------

    def _row_index_at(self, pos) -> Optional[int]:
        item = self.table.itemAt(pos)
        if item is None:
            return None
        return self.table.item(item.row(), COL_FILE).data(Qt.UserRole)

    def _show_context_menu(self, pos):
        idx = self._row_index_at(pos)
        if idx is None or (self._alt_worker is not None and self._alt_worker.isRunning()):
            return
        menu = QMenu(self)
        retry = menu.addAction("Wrong match — try again")
        manual = menu.addAction("Wrong match — enter tags myself...")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == retry:
            self._mark_wrong(idx, search=True)
        elif chosen == manual:
            self._mark_wrong(idx, search=False)

    def _table_row_for(self, idx: int) -> Optional[int]:
        for r in range(self.table.rowCount()):
            if self.table.item(r, COL_FILE).data(Qt.UserRole) == idx:
                return r
        return None

    def _mark_wrong(self, idx: int, search: bool):
        row = self._table_row_for(idx)
        if row is None:
            return
        track = self._rows[idx][0]
        artist = self.table.item(row, COL_ARTIST).text().strip()
        title = self.table.item(row, COL_TITLE).text().strip()
        self._rejected.setdefault(idx, set()).add((artist, title))
        # A wrong match shouldn't get written by accident.
        self.table.item(row, COL_INCLUDE).setCheckState(Qt.Unchecked)
        if not search:
            self._show_correction(idx, [])
            return
        self.setCursor(Qt.BusyCursor)
        worker = AlternativesWorker(track, self._rejected[idx], self)
        self._alt_worker = worker

        def done(found):
            self.unsetCursor()
            self._show_correction(idx, found)

        worker.finished_lookup.connect(done)
        worker.start()

    def _show_correction(self, idx: int, candidates):
        row = self._table_row_for(idx)
        if row is None:
            return
        track = self._rows[idx][0]
        dlg = CorrectionDialog(
            track.filename,
            candidates,
            artist=self.table.item(row, COL_ARTIST).text(),
            title=self.table.item(row, COL_TITLE).text(),
            album=self.table.item(row, COL_ALBUM).text(),
            parent=self,
        )
        if not dlg.exec():
            return
        tags = dlg.result_tags()
        if tags is None:
            QMessageBox.information(self, "Nothing Entered", "Artist and title are both required.")
            return
        artist, title, album, source = tags
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)  # otherwise the row can jump while its cells are being updated
        row = self._table_row_for(idx)
        self.table.item(row, COL_ARTIST).setText(artist)
        self.table.item(row, COL_TITLE).setText(title)
        self.table.item(row, COL_ALBUM).setText(album)
        self.table.item(row, COL_SOURCE).setText(_SOURCE_LABELS.get(source, source))
        self.table.item(row, COL_CONFIDENCE).setData(Qt.DisplayRole, 100 if source == "manual" else self.table.item(row, COL_CONFIDENCE).data(Qt.DisplayRole))
        self.table.item(row, COL_INCLUDE).setCheckState(Qt.Checked)
        self.table.setSortingEnabled(sorting)

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
        for row in range(self.table.rowCount()):
            if self.table.item(row, COL_INCLUDE).checkState() != Qt.Checked:
                continue
            track = self._rows[self.table.item(row, COL_FILE).data(Qt.UserRole)][0]

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

        progress = QProgressDialog("Writing tags...", "Cancel", 0, len(to_write), self)
        progress.setWindowTitle("Writing Tags")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        worker = TagWriteWorker(to_write, self)
        self._write_worker = worker
        worker.progress.connect(lambda done, total: progress.setValue(done))
        progress.canceled.connect(worker.cancel)

        def on_finished(written, errors):
            progress.close()
            summary_lines = [f"Wrote tags to {written} file(s)."]
            if errors:
                summary_lines.append(f"\n{len(errors)} failed:")
                summary_lines.extend(f"  {e}" for e in errors[:20])
            QMessageBox.information(self, "Tag Write Complete", "\n".join(summary_lines))
            self.accept()

        worker.finished_write.connect(on_finished)
        worker.start()
