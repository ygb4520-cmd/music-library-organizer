"""Tiny helper to audition the first few seconds of a track, so the user can
tell whether two files are really the same song. Uses Qt Multimedia; if it
isn't available the player reports that instead of raising."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl


class SnippetPlayer:
    def __init__(self, parent=None, seconds: int = 5):
        self.seconds = seconds
        self.error: str | None = None
        self._player = None
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.stop)
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._player = QMediaPlayer(parent)
            self._audio = QAudioOutput(parent)
            self._player.setAudioOutput(self._audio)
        except Exception as exc:  # Qt Multimedia missing / no audio backend
            self.error = str(exc)

    def play(self, path: Path) -> bool:
        if self._player is None:
            return False
        self.stop()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.setPosition(0)
        self._player.play()
        self._timer.start(self.seconds * 1000)
        return True

    def stop(self) -> None:
        self._timer.stop()
        if self._player is not None:
            self._player.stop()
