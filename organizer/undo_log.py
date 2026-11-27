"""Undo log for file moves.

Each move run writes one JSON file (source, destination, timestamp per move,
plus the empty folders cleanup removed) under the user's local app data
folder. `undo_last_run()` reverses the most recent log, in reverse order, and
never overwrites anything: a file that is no longer at its destination, or
whose original location is occupied, is skipped and reported.

Out of scope: undoing tag writes.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

LOG_VERSION = 1
UNDONE_SUFFIX = ".undone"
FLUSH_EVERY = 20  # moves between log writes while a run is in progress


def get_undo_dir() -> Path:
    """%LOCALAPPDATA%\\MusicLibraryOrganizer\\undo on Windows (platform
    equivalents elsewhere). MLO_UNDO_DIR overrides it (used by the tests)."""
    override = os.environ.get("MLO_UNDO_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "MusicLibraryOrganizer" / "undo"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write to a temp file in the same folder, then rename over the target,
    so a crash never leaves a half-written log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class UndoLog:
    """Records one move run. Never raises: logging problems must not stop a move."""

    def __init__(self, source_root: Path, undo_dir: Optional[Path] = None):
        self.undo_dir = Path(undo_dir) if undo_dir else get_undo_dir()
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        self.path = self.undo_dir / f"run-{stamp}.json"
        self.data = {
            "version": LOG_VERSION,
            "started": _now(),
            "source_root": str(source_root),
            "moves": [],
            "removed_dirs": [],
            "completed": False,
        }
        self._unflushed = 0
        self.error: Optional[str] = None
        self._flush()

    def _flush(self) -> None:
        try:
            _atomic_write_json(self.path, self.data)
            self._unflushed = 0
        except Exception as exc:
            self.error = str(exc)

    def record_move(self, source: Path, destination: Path) -> None:
        self.data["moves"].append(
            {"source": str(source), "destination": str(destination), "timestamp": _now()}
        )
        self._unflushed += 1
        if self._unflushed >= FLUSH_EVERY:
            self._flush()

    def finish(self, removed_dirs: List[Path]) -> None:
        self.data["removed_dirs"] = [str(p) for p in removed_dirs]
        self.data["completed"] = True
        if not self.data["moves"] and not self.data["removed_dirs"]:
            try:  # nothing happened; don't leave an empty log to "undo"
                self.path.unlink()
                return
            except OSError:
                pass
        self._flush()


class UndoResult:
    def __init__(self):
        self.restored: List[str] = []
        self.skipped: List[tuple] = []  # (path, reason)
        self.recreated_dirs: List[str] = []
        self.log_path: Optional[Path] = None
        self.error: Optional[str] = None


def find_latest_log(undo_dir: Optional[Path] = None) -> Optional[Path]:
    d = Path(undo_dir) if undo_dir else get_undo_dir()
    try:
        logs = sorted(p for p in d.glob("run-*.json"))
    except OSError:
        return None
    return logs[-1] if logs else None


def load_log(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("moves"), list):
        raise ValueError("Unrecognized undo log format.")
    return data


def undo_last_run(undo_dir: Optional[Path] = None) -> UndoResult:
    result = UndoResult()
    path = find_latest_log(undo_dir)
    if path is None:
        result.error = "There is no move to undo."
        return result
    result.log_path = path
    try:
        data = load_log(path)
    except Exception as exc:
        result.error = f"Could not read the undo log ({path.name}): {exc}"
        return result

    # Recreate folders cleanup removed (shallowest first) before restoring files.
    for d in sorted((Path(p) for p in data.get("removed_dirs", [])), key=lambda p: len(p.parts)):
        try:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                result.recreated_dirs.append(str(d))
        except OSError:
            pass  # restoring files below creates parents anyway

    for move in reversed(data["moves"]):
        src, dest = Path(move["source"]), Path(move["destination"])
        try:
            if not os.path.lexists(dest):
                result.skipped.append((str(dest), "no longer at its destination (moved or deleted since)"))
                continue
            if os.path.lexists(src):
                result.skipped.append((str(dest), f"original location is occupied: {src}"))
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(src))
            result.restored.append(str(src))
        except Exception as exc:
            result.skipped.append((str(dest), f"error: {exc}"))

    # Mark the log as used so the next undo targets the run before it.
    try:
        os.replace(path, path.with_name(path.stem + UNDONE_SUFFIX + ".json.bak"))
    except OSError:
        pass
    return result
