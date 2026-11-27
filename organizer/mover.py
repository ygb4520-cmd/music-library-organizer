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
from .undo_log import UndoLog


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

    @staticmethod
    def _key(path: Path) -> str:
        try:
            return os.path.normcase(str(path.resolve()))
        except OSError:
            return os.path.normcase(str(path.absolute()))

    def run(self):
        """Moves items in rounds. A move whose destination is occupied by the source of another item that has not
        moved yet is deferred and retried once that item is out of the way; only a destination that stays occupied
        (by an unrelated file, or by a file that itself can't move) is an error. Nothing is ever overwritten."""
        result = MoveResult()
        total = len(self.items)
        undo = UndoLog(self.source_root)
        processed = 0
        pending = list(self.items)

        while pending and not self._cancelled:
            pending_sources = {self._key(it.source_path) for it in pending}
            deferred: List[PlanItem] = []
            for item in pending:
                if self._cancelled:
                    break
                try:
                    dest = item.dest_path
                    if dest.resolve() == item.source_path.resolve():
                        # Already correctly placed -- nothing to do.
                        result.already_in_place.append(item)
                    elif dest.exists():
                        if self._key(dest) in pending_sources:
                            deferred.append(item)  # occupied by a file that is still waiting to move -- try again later
                            continue
                        raise FileExistsError(f"Destination already exists: {dest}")
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(item.source_path), str(dest))
                        undo.record_move(item.source_path, dest)
                        result.moved.append(item)
                except Exception as exc:
                    item.move_error = str(exc)
                    result.failed.append(item)
                # Finished with this item (moved, in place or failed): it no longer blocks anyone's destination.
                pending_sources.discard(self._key(item.source_path))
                processed += 1
                self.progress.emit(processed, total)

            if self._cancelled:
                break
            if len(deferred) == len(pending):
                # A full round with no progress: what's left is blocked by each other (e.g. a swap).
                for item in deferred:
                    item.move_error = (
                        f"Destination is occupied by another file that is also waiting to move "
                        f"(circular swap, nothing was overwritten): {item.dest_path}"
                    )
                    result.failed.append(item)
                    processed += 1
                    self.progress.emit(processed, total)
                break
            pending = deferred

        result.cleaned_dirs = self._cleanup_empty_dirs()
        undo.finish(result.cleaned_dirs)
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
