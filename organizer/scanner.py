"""Threaded recursive scan of a source folder: finds audio files, reads tags,
and applies filename/folder fallback inference. Runs off the UI thread so the
window stays responsive on large libraries."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from . import inference, tag_reader
from .models import TrackInfo


class ScanWorker(QThread):
    progress = Signal(int, int)  # (files_processed, total_files)
    finished_scan = Signal(list)  # List[TrackInfo]
    failed = Signal(str)

    def __init__(self, source_root: Path, parent=None):
        super().__init__(parent)
        self.source_root = Path(source_root)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            paths: List[Path] = []
            for dirpath, _dirnames, filenames in os.walk(self.source_root):
                if self._cancelled:
                    return
                for name in filenames:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in tag_reader.SUPPORTED_EXTENSIONS:
                        paths.append(Path(dirpath) / name)

            total = len(paths)
            tracks: List[TrackInfo] = []
            for i, path in enumerate(paths, start=1):
                if self._cancelled:
                    return
                track = tag_reader.read_tags(path)
                inference.apply_fallback(track, self.source_root)
                tracks.append(track)
                self.progress.emit(i, total)

            self.finished_scan.emit(tracks)
        except Exception as exc:
            self.failed.emit(str(exc))
