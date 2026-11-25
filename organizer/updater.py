"""Self-update: checks GitHub Releases for a newer version and, if the user
confirms, downloads and installs it in place.

Only meaningful when running as the frozen PyInstaller .exe (sys.frozen) --
there's nothing sensible to self-replace when running from source during
development on macOS, so update checks are a no-op there.
"""
from __future__ import annotations

import hashlib
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
# Only ever install a file that comes from this repo's own release downloads.
TRUSTED_DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"


def is_trusted_asset_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith(TRUSTED_DOWNLOAD_PREFIX)


def parse_sha256_text(text: str):
    """First 64-hex-digit token in a `sha256sum`-style file, lowercased, or None."""
    for token in text.split():
        t = token.strip().lower()
        if len(t) == 64 and all(c in "0123456789abcdef" for c in t):
            return t
    return None


def sha256_of_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        if asset is None or not is_trusted_asset_url(asset.get("browser_download_url", "")):
            self.no_update.emit()
            return

        self.found_update.emit(latest_version.lstrip("v"), asset["browser_download_url"])


class UpdateApplyWorker(QThread):
    progress_text = Signal(str)
    # (bytes downloaded, total bytes; total is 0 when the server doesn't say)
    download_progress = Signal(int, int)
    failed = Signal(str)
    # No "succeeded" signal -- success means a helper process is about to
    # relaunch the app under a new PID, so the caller should just quit.

    def __init__(self, asset_url: str, parent=None):
        super().__init__(parent)
        self.asset_url = asset_url

    def _download(self, url: str, dest: Path):
        with urllib.request.urlopen(url, timeout=30) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            self.download_progress.emit(0, total)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                self.download_progress.emit(done, total)
                self.progress_text.emit(
                    f"Downloading update… {done / 1048576:.1f}"
                    + (f" / {total / 1048576:.1f}" if total else "")
                    + " MB"
                )

    def run(self):
        try:
            self.progress_text.emit("Downloading update…")
            tmp_dir = Path(tempfile.mkdtemp(prefix="mlo-update-"))
            new_exe = tmp_dir / "MusicLibraryOrganizer-new.exe"
            if not is_trusted_asset_url(self.asset_url):
                raise RuntimeError("Update download is not from the official release; refusing to install it.")
            self._download(self.asset_url, new_exe)

            # Integrity check: the release publishes <exe name>.sha256 next to
            # the exe. No checksum, or a mismatch, means we do NOT install.
            self.progress_text.emit("Verifying download…")
            try:
                with urllib.request.urlopen(self.asset_url + ".sha256", timeout=15) as resp:
                    expected = parse_sha256_text(resp.read(4096).decode("utf-8", "replace"))
            except Exception:
                expected = None
            if expected is None:
                raise RuntimeError("This release has no checksum file, so the download can't be verified. Not installing.")
            if sha256_of_file(new_exe) != expected:
                raise RuntimeError("Downloaded update failed its checksum check (corrupt or tampered). Not installing.")

            current_exe = Path(sys.executable)

            # Windows won't let a running process overwrite its own .exe
            # file, so we spawn a hidden helper that waits until the old exe
            # can actually be replaced, swaps the files, relaunches the app,
            # then deletes itself. A PyInstaller one-file exe runs as TWO
            # processes (a bootloader parent plus this one) and the parent
            # keeps the file locked a moment after this PID exits, so we
            # retry the move instead of trusting a single attempt.
            helper_path = tmp_dir / "apply_update.bat"
            log_path = tmp_dir / "update.log"
            helper_path.write_text(
                "@echo off\r\n"
                f'echo Update started > "{log_path}"\r\n'
                "set TRIES=0\r\n"
                # Give the old process a moment to exit. No tasklist|find here:
                # those spawned visible console windows (one titled "find <pid>"
                # that never closed). The move below simply fails while the
                # exe is still locked, and we retry it.
                "ping -n 3 127.0.0.1 >nul\r\n"
                ":swap\r\n"
                f'move /y "{new_exe}" "{current_exe}" >> "{log_path}" 2>&1\r\n'
                "if not errorlevel 1 goto done\r\n"
                "set /a TRIES+=1\r\n"
                "if %TRIES% geq 60 goto done\r\n"
                "ping -n 2 127.0.0.1 >nul\r\n"
                "goto swap\r\n"
                ":done\r\n"
                # Stop the relaunched app from reusing the old process's
                # extracted temp folder (which is gone by now).
                "set PYINSTALLER_RESET_ENVIRONMENT=1\r\n"
                "set _MEIPASS2=\r\n"
                f'start "" "{current_exe}"\r\n'
                'del "%~f0"\r\n'
            )

            self.progress_text.emit("Installing update…")
            # CREATE_NO_WINDOW alone gives cmd a hidden console that its child
            # processes inherit. DETACHED_PROCESS would leave no console, so
            # every child (ping, move...) would pop up its own visible one.
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            CREATE_NO_WINDOW = 0x08000000
            env = os.environ.copy()
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            env.pop("_MEIPASS2", None)
            subprocess.Popen(
                ["cmd", "/c", str(helper_path)],
                creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                close_fds=True,
                env=env,
            )
        except Exception as e:
            self.failed.emit(str(e))
