"""Online metadata lookup for tracks with no/unknown tags, via MusicBrainz's
free search API. Guesses artist/title from the filename (reusing the same
pattern-matching already used for folder-placement fallback), then queries
MusicBrainz for a matching recording.

This module only *looks up* candidates -- it never writes anything to a
file. Writing is a separate, explicit, user-confirmed step (tag_writer.py +
the preview dialog), matching the app's core principle of never silently
modifying tags.

Uses the standard library only (urllib), no new dependency, consistent with
the app's existing minimal footprint.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import inference

MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
# MusicBrainz's usage policy requires a descriptive User-Agent identifying
# the application; requests without one are more likely to be rate-limited
# or blocked. No API key needed for this level of usage.
USER_AGENT = "MusicLibraryOrganizer/0.1 (personal-use desktop app)"
# MusicBrainz asks for at most ~1 request/second for unauthenticated use.
MIN_SECONDS_BETWEEN_REQUESTS = 1.1
MIN_CONFIDENT_SCORE = 80  # MusicBrainz's own 0-100 relevance score


@dataclass
class MatchCandidate:
    score: int
    artist: str
    title: str
    album: Optional[str]

    @property
    def is_confident(self) -> bool:
        return self.score >= MIN_CONFIDENT_SCORE


def guess_query(path: Path) -> Optional[tuple[str, str]]:
    """Returns (artist, title) guessed from the filename, or None if the
    filename doesn't contain enough to search with (no title at all)."""
    guessed = inference.guess_from_filename(path.stem)
    title = guessed.get("title")
    if not title:
        return None
    return guessed.get("artist") or "", title


def search(artist: str, title: str, timeout: float = 10.0) -> list[MatchCandidate]:
    """Queries MusicBrainz for recordings matching artist+title. Returns
    candidates sorted by score (highest first), possibly empty."""
    query_parts = [f'recording:"{title}"']
    if artist:
        query_parts.append(f'artist:"{artist}"')
    query = " AND ".join(query_parts)

    params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 5})
    url = f"{MUSICBRAINZ_SEARCH_URL}?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    # One retry after a short backoff: a transient rate-limit/network hiccup
    # (observed in testing -- MusicBrainz occasionally rejects a request
    # queried too soon after a prior one) would otherwise look identical to
    # "this song genuinely isn't in MusicBrainz", which is misleading.
    data = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
            break
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            # OSError covers socket.timeout too -- on Python <3.10 that's a
            # distinct exception from TimeoutError, not a subclass of it, so
            # catching only TimeoutError silently missed real network timeouts.
            if attempt == 0:
                time.sleep(2.0)
                continue
            return []

    candidates = []
    for recording in data.get("recordings", []):
        score = int(recording.get("score", 0))
        rec_title = recording.get("title")
        artist_credit = recording.get("artist-credit", [])
        rec_artist = artist_credit[0]["name"] if artist_credit else None
        releases = recording.get("releases", [])
        rec_album = releases[0]["title"] if releases else None

        if not rec_title or not rec_artist:
            continue

        candidates.append(MatchCandidate(score=score, artist=rec_artist, title=rec_title, album=rec_album))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def best_match(path: Path, timeout: float = 10.0) -> Optional[MatchCandidate]:
    """Convenience wrapper: guess a query from the filename, search, and
    return the single best candidate (regardless of confidence -- callers
    decide what to do with a low-confidence match, typically via
    MatchCandidate.is_confident)."""
    guessed = guess_query(path)
    if guessed is None:
        return None
    artist, title = guessed
    candidates = search(artist, title, timeout=timeout)
    return candidates[0] if candidates else None
