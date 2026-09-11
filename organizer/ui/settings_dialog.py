"""App preferences: default sort order for the metadata lookup preview,
default multi-artist handling, and the AcoustID API key used for the
audio-fingerprinting fallback. Saved via organizer/settings.py (QSettings)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .. import settings


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(480, 220)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.sort_combo = QComboBox()
        for value in settings.SORT_OPTIONS:
            self.sort_combo.addItem(settings.SORT_LABELS[value], value)
        current_sort = settings.get_sort_order()
        self.sort_combo.setCurrentIndex(settings.SORT_OPTIONS.index(current_sort))
        form.addRow("Sort metadata results by:", self.sort_combo)

        self.multi_artist_combo = QComboBox()
        for value in settings.MULTI_ARTIST_OPTIONS:
            self.multi_artist_combo.addItem(settings.MULTI_ARTIST_LABELS[value], value)
        current_mode = settings.get_multi_artist_mode()
        self.multi_artist_combo.setCurrentIndex(settings.MULTI_ARTIST_OPTIONS.index(current_mode))
        form.addRow("Multiple-artist tracks, by default:", self.multi_artist_combo)

        self.acoustid_edit = QLineEdit(settings.get_acoustid_api_key())
        self.acoustid_edit.setPlaceholderText("Paste your free AcoustID API key")
        form.addRow("AcoustID API key:", self.acoustid_edit)

        layout.addLayout(form)

        note = QLabel(
            "Used only for the audio-fingerprinting fallback when a filename-based "
            "metadata search finds no confident match. Free at acoustid.org/api-key. "
            "Leave blank to skip fingerprinting and rely on filename search only."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        settings.set_sort_order(self.sort_combo.currentData())
        settings.set_multi_artist_mode(self.multi_artist_combo.currentData())
        settings.set_acoustid_api_key(self.acoustid_edit.text().strip())
        self.accept()
