"""Threaded recursive scan of a source folder: finds audio files, reads tags,
applies filename/folder fallback inference, and builds the move plan
(destination paths + duplicate/conflict flagging). Runs off the UI thread so
the window stays responsive on large libraries -- this now includes
planner.build_plan() rather than just tag reading, because duplicate
detection can call out to AcoustID for audio-fingerprint identification
(see planner._group_by_fingerprint) when a key is configured, and that
network round-trip per file must not block the GUI thread any more than tag
reading does."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from . import inference, planner, tag_reader
from .models import TrackInfo


class ScanWorker(QThread):
    progress = Signal(int, int)  # (files_processed, total_files)
    finished_scan = Signal(list)  # List[PlanItem]
    failed = Signal(str)

    def __init__(self, source_root: Path, destination_root: Path, parent=None):
        super().__init__(parent)
        self.source_root = Path(source_root)
        self.destination_root = Path(destination_root)
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

            if self._cancelled:
                return
            items = planner.build_plan(
                tracks, self.source_root, self.destination_root, is_cancelled=lambda: self._cancelled
            )
            if self._cancelled:
                return
            self.finished_scan.emit(items)
        except Exception as exc:
            self.failed.emit(str(exc))
