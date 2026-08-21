"""Self-update: checks GitHub Releases for a newer version and, if the user
confirms, downloads and installs it in place.

Only meaningful when running as the frozen PyInstaller .exe (sys.frozen) --
there's nothing sensible to self-replace when running from source during
development on macOS, so update checks are a no-op there.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .__version__ import __version__

REPO = "ygb4520-cmd/music-library-organizer"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"


def is_frozen() -> bool:
    """True when running as the PyInstaller-built .exe, not `python main.py`."""
    return bool(getattr(sys, "frozen", False))


def _parse_version(v: str):
    return [int(p) if p.isdigit() else 0 for p in v.lstrip("v").split(".")]


def _is_newer(latest: str, current: str) -> bool:
    lp, cp = _parse_version(latest), _parse_version(current)
    length = max(len(lp), len(cp))
    lp += [0] * (length - len(lp))
    cp += [0] * (length - len(cp))
    return lp > cp


class UpdateCheckWorker(QThread):
    """Runs off the UI thread so a slow/unreachable GitHub never freezes the
    window, matching this app's existing ScanWorker/MoveWorker pattern."""

    found_update = Signal(str, str)  # (version, asset_download_url)
    no_update = Signal()

    def run(self):
        if not is_frozen():
            self.no_update.emit()
            return
        try:
            req = urllib.request.Request(
                RELEASES_API, headers={"Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                release = json.load(resp)
        except Exception:
            # Offline or GitHub unreachable -- fail silently, not worth
            # interrupting the user's workflow over.
            self.no_update.emit()
            return

        latest_version = release.get("tag_name", "")
        if not latest_version or not _is_newer(latest_version, __version__):
            self.no_update.emit()
            return

        asset = next(
            (a for a in release.get("assets", []) if a["name"].endswith(".exe")), None
        )
        if asset is None:
            self.no_update.emit()
            return

        self.found_update.emit(latest_version.lstrip("v"), asset["browser_download_url"])


class UpdateApplyWorker(QThread):
    progress_text = Signal(str)
    failed = Signal(str)
    # No "succeeded" signal -- success means a helper process is about to
    # relaunch the app under a new PID, so the caller should just quit.

    def __init__(self, asset_url: str, parent=None):
        super().__init__(parent)
        self.asset_url = asset_url

    def run(self):
        try:
            self.progress_text.emit("Downloading update…")
            tmp_dir = Path(tempfile.mkdtemp(prefix="mlo-update-"))
            new_exe = tmp_dir / "MusicLibraryOrganizer-new.exe"
            urllib.request.urlretrieve(self.asset_url, new_exe)

            current_exe = Path(sys.executable)
            pid = os.getpid()

            # Windows won't let a running process overwrite its own .exe
            # file, so we spawn a detached helper that waits for this
            # process to fully exit, swaps the files, relaunches the app,
            # then deletes itself.
            helper_path = tmp_dir / "apply_update.bat"
            helper_path.write_text(
                "@echo off\r\n"
                ":wait\r\n"
                f'tasklist /fi "PID eq {pid}" | find "{pid}" >nul\r\n'
                "if not errorlevel 1 (\r\n"
                "  timeout /t 1 /nobreak >nul\r\n"
                "  goto wait\r\n"
                ")\r\n"
                f'move /y "{new_exe}" "{current_exe}"\r\n'
                f'start "" "{current_exe}"\r\n'
                'del "%~f0"\r\n'
            )

            self.progress_text.emit("Installing update…")
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(
                ["cmd", "/c", str(helper_path)],
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        except Exception as e:
            self.failed.emit(str(e))
