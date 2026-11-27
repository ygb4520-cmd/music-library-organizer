"""Shown when the user marks a suggested match as wrong: lists other candidates found online (if any) and lets
the user pick one or simply type the correct tags by hand."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..metadata_lookup import MatchCandidate


class CorrectionDialog(QDialog):
    def __init__(self, filename: str, candidates: List[MatchCandidate], artist: str = "", title: str = "",
                 album: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correct Match")
        self.resize(520, 400)
        self.candidates = candidates

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{filename}</b>"))

        if candidates:
            layout.addWidget(QLabel("Other possible matches (pick one, or type the tags below):"))
            self.list = QListWidget()
            for c in candidates:
                text = f"{c.artist} — {c.title}" + (f"  [{c.album}]" if c.album else "")
                text += f"   ({c.score}%, {'Fingerprint' if c.source == 'fingerprint' else 'Filename'})"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, c)
                self.list.addItem(item)
            self.list.currentRowChanged.connect(self._on_pick)
            layout.addWidget(self.list, 1)
        else:
            self.list = None
            layout.addWidget(QLabel("No other matches were found. Enter the correct tags by hand:"))

        form = QFormLayout()
        self.artist_edit = QLineEdit(artist)
        self.title_edit = QLineEdit(title)
        self.album_edit = QLineEdit(album)
        form.addRow("Artist:", self.artist_edit)
        form.addRow("Title:", self.title_edit)
        form.addRow("Album:", self.album_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_pick(self, row: int):
        if row < 0 or self.list is None:
            return
        c = self.list.item(row).data(Qt.UserRole)
        self.artist_edit.setText(c.artist)
        self.title_edit.setText(c.title)
        self.album_edit.setText(c.album or "")

    def result_tags(self) -> Optional[tuple]:
        """(artist, title, album, source) or None if nothing usable was entered. source is 'manual' unless an
        untouched candidate was chosen."""
        artist = self.artist_edit.text().strip()
        title = self.title_edit.text().strip()
        album = self.album_edit.text().strip()
        if not artist or not title:
            return None
        source = "manual"
        if self.list is not None and self.list.currentRow() >= 0:
            c = self.list.item(self.list.currentRow()).data(Qt.UserRole)
            if (c.artist, c.title, c.album or "") == (artist, title, album):
                source = c.source
        return artist, title, album, source
