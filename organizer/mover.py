"""Threaded execution of the move plan, plus post-move empty-directory
cleanup under the source root. Only ever moves files that are still marked
`include=True` at the moment the user confirms."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from .models import PlanItem


class MoveResult:
    def __init__(self):
        self.moved: List[PlanItem] = []
        self.already_in_place: List[PlanItem] = []
        self.failed: List[PlanItem] = []
        self.cleaned_dirs: List[Path] = []


class MoveWorker(QThread):
    progress = Signal(int, int)  # (files_processed, total_files)
    finished_move = Signal(object)  # MoveResult

    def __init__(self, items: List[PlanItem], source_root: Path, parent=None):
        super().__init__(parent)
        self.items = [i for i in items if i.include and i.dest_path is not None]
        self.source_root = Path(source_root)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        result = MoveResult()
        total = len(self.items)

        for i, item in enumerate(self.items, start=1):
            if self._cancelled:
                break
            try:
                dest = item.dest_path
                if dest.resolve() == item.source_path.resolve():
                    # Already correctly placed -- nothing to do.
                    result.already_in_place.append(item)
                    self.progress.emit(i, total)
                    continue
                if dest.exists():
                    raise FileExistsError(f"Destination already exists: {dest}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item.source_path), str(dest))
                result.moved.append(item)
            except Exception as exc:
                item.move_error = str(exc)
                result.failed.append(item)
            self.progress.emit(i, total)

        result.cleaned_dirs = self._cleanup_empty_dirs()
        self.finished_move.emit(result)

    def _cleanup_empty_dirs(self) -> List[Path]:
        removed: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.source_root, topdown=False):
            path = Path(dirpath)
            if path == self.source_root:
                continue
            try:
                if not any(path.iterdir()):
                    path.rmdir()
                    removed.append(path)
            except OSError:
                continue
        return removed
