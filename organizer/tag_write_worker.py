"""Threaded batch tag writing, so writing many files (slow disks/network
shares) doesn't freeze the UI. Matches the app's other QThread workers."""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QThread, Signal

from . import tag_writer
from .models import TrackInfo


class TagWriteWorker(QThread):
    progress = Signal(int, int)  # (done, total)
    finished_write = Signal(int, list)  # (written count, error strings)

    def __init__(self, items: List[Tuple[TrackInfo, str, str, str]], parent=None):
        super().__init__(parent)
        self.items = items
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.items)
        written = 0
        errors: List[str] = []
        for i, (track, artist, title, album) in enumerate(self.items, 1):
            if self._cancelled:
                break
            try:
                tag_writer.write_tags(track.path, artist=artist, title=title, album=album)
                written += 1
            except tag_writer.TagWriteError as e:
                errors.append(f"{track.filename}: {e}")
            except Exception as e:  # never let one bad file kill the batch
                errors.append(f"{track.filename}: {e}")
            self.progress.emit(i, total)
        self.finished_write.emit(written, errors)
