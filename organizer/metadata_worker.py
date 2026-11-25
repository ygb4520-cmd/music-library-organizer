"""Threaded MusicBrainz lookup for tracks with no/unknown tags. Runs off the
UI thread since network round-trips (plus the required ~1/sec rate limit)
would otherwise freeze the window, matching this app's existing
ScanWorker/MoveWorker pattern."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from . import metadata_lookup, settings
from .models import TrackInfo

# Parallel lookups: fpcalc (local CPU) and network waits overlap across threads;
# MusicBrainz (1/s) and AcoustID (3/s) limits are enforced globally by RateLimiters.
_MAX_WORKERS = 4


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
            total = len(self.tracks)
            api_key = settings.get_acoustid_api_key()
            results: List[Tuple[TrackInfo, Optional[metadata_lookup.MatchCandidate]]] = [None] * total  # type: ignore

            def work(i: int):
                if self._cancelled:
                    return i, None
                t = self.tracks[i]
                try:
                    m = metadata_lookup.best_match(
                        t.path, known_artist=t.artist, known_title=t.title, api_key=api_key or ""
                    )
                except Exception:
                    m = None
                return i, m

            done = 0
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                futures = [pool.submit(work, i) for i in range(total)]
                for fut in futures:
                    i, m = fut.result()
                    results[i] = (self.tracks[i], m)
                    done += 1
                    if self._cancelled:
                        for f in futures:
                            f.cancel()
                        return
                    self.progress.emit(done, total)

            self.finished_lookup.emit(results)
        except Exception as e:
            self.failed.emit(str(e))
