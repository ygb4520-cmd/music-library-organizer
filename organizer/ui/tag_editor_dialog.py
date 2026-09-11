"""Standalone manual tag editor -- lets you fix/set artist, title, album,
album artist, and track number directly for any scanned file, independent
of the online metadata-lookup flow. Writes only on explicit Save, using the
same tag_writer.write_tags() as the lookup dialog (the only two places in
the app that touch tags on disk)."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout

from .. import tag_writer
from ..models import TrackInfo


class TagEditorDialog(QDialog):
    def __init__(self, track: TrackInfo, parent=None):
        super().__init__(parent)
        self.track = track
        self.setWindowTitle(f"Edit Tags — {track.filename}")
        self.resize(420, 220)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{track.filename}</b>"))

        form = QFormLayout()
        self.artist_edit = QLineEdit(track.artist or "")
        self.title_edit = QLineEdit(track.title or "")
        self.album_edit = QLineEdit(track.album or "")
        self.album_artist_edit = QLineEdit(track.album_artist or "")
        self.track_number_edit = QLineEdit(track.track_number or "")

        form.addRow("Artist:", self.artist_edit)
        form.addRow("Title:", self.title_edit)
        form.addRow("Album:", self.album_edit)
        form.addRow("Album Artist:", self.album_artist_edit)
        form.addRow("Track #:", self.track_number_edit)
        layout.addLayout(form)

        if not tag_writer.can_write_tags(track.ext):
            note = QLabel(f"Writing tags to {track.ext} files isn't supported — this file can be viewed but not saved.")
            note.setWordWrap(True)
            layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if not tag_writer.can_write_tags(track.ext):
            buttons.button(QDialogButtonBox.Save).setEnabled(False)

    def _save(self):
        try:
            tag_writer.write_tags(
                self.track.path,
                artist=self.artist_edit.text(),
                title=self.title_edit.text(),
                album=self.album_edit.text(),
                album_artist=self.album_artist_edit.text(),
                track_number=self.track_number_edit.text(),
            )
        except tag_writer.TagWriteError as e:
            QMessageBox.critical(self, "Save Failed", str(e))
            return
        self.accept()
