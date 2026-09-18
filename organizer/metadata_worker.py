"""Threaded MusicBrainz lookup for tracks with no/unknown tags. Runs off the
UI thread since network round-trips (plus the required ~1/sec rate limit)
would otherwise freeze the window, matching this app's existing
ScanWorker/MoveWorker pattern."""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from . import metadata_lookup
from .models import TrackInfo

# Keep in sync with metadata_lookup.MIN_SECONDS_BETWEEN_REQUESTS -- this is
# the pacing the worker sleeps between requests, not a duplicate policy.
_REQUEST_SPACING = metadata_lookup.MIN_SECONDS_BETWEEN_REQUESTS


class MetadataLookupWorker(QThread):
    progress = Signal(int, int)  # (done, total)
    finished_lookup = Signal(list)  # List[Tuple[TrackInfo, Optional[MatchCandidate]]]
    failed = Signal(str)

    def __init__(self, tracks: List[TrackInfo], parent=None):
        super().__init__(parent)
        self.tracks = tracks
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            results: List[Tuple[TrackInfo, Optional[metadata_lookup.MatchCandidate]]] = []
            total = len(self.tracks)

            for i, track in enumerate(self.tracks):
                if self._cancelled:
                    return

                match = metadata_lookup.best_match(
                    track.path, known_artist=track.artist, known_title=track.title
                )
                results.append((track, match))

                self.progress.emit(i + 1, total)

                # Only sleep between requests, not after the last one.
                if i + 1 < total:
                    time.sleep(_REQUEST_SPACING)

            self.finished_lookup.emit(results)
        except Exception as e:
            self.failed.emit(str(e))
