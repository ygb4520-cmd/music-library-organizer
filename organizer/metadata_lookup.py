"""Online metadata lookup for tracks with no/unknown tags.

Two strategies, tried in order:
1. Filename-based text search against MusicBrainz's free API (guesses
   artist/title from the filename, reusing the same pattern-matching
   already used for folder-placement fallback). Fast, no extra setup.
2. If that finds nothing confident, and an AcoustID API key is configured
   (Settings), fall back to audio fingerprinting: identifies the song from
   its actual audio content via the bundled `fpcalc` binary + AcoustID's
   API, regardless of filename quality. Slower (has to read the audio),
   and needs the free API key, which is why it's a fallback, not the
   default.

This module only *looks up* candidates -- it never writes anything to a
file. Writing is a separate, explicit, user-confirmed step (tag_writer.py +
the preview dialog), matching the app's core principle of never silently
modifying tags.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import acoustid

from . import inference, settings

MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
# MusicBrainz's usage policy requires a descriptive User-Agent identifying
# the application; requests without one are more likely to be rate-limited
# or blocked. No API key needed for this level of usage.
USER_AGENT = "MusicLibraryOrganizer/0.1 (personal-use desktop app)"
# MusicBrainz asks for at most ~1 request/second for unauthenticated use.
MIN_SECONDS_BETWEEN_REQUESTS = 1.1
MIN_CONFIDENT_SCORE = 80  # 0-100 scale, shared by both strategies below

# AcoustID's own match score is 0.0-1.0, not MusicBrainz's 0-100 -- it gets
# multiplied by 100 in fingerprint_match() so MIN_CONFIDENT_SCORE above
# applies uniformly regardless of which strategy found the match.


@dataclass
class MatchCandidate:
    score: int
    artist: str
    title: str
    album: Optional[str]
    source: str = "filename"  # "filename" or "fingerprint" -- shown in the preview UI

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


def fpcalc_path() -> str:
    """Resolves the bundled fpcalc binary for the current platform. Handles
    both running from source (dev mode) and running as a frozen PyInstaller
    .exe, where bundled data files are extracted to sys._MEIPASS at runtime
    rather than living next to this source file."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent  # project root

    if sys.platform == "win32":
        return str(base / "bin" / "windows" / "fpcalc.exe")
    return str(base / "bin" / "mac" / "fpcalc")


def fingerprint_match(path: Path, api_key: str, timeout: float = 30.0) -> Optional[MatchCandidate]:
    """Identifies a track from its actual audio content via AcoustID,
    regardless of filename. Slower than the filename search (has to read
    the audio to compute a fingerprint) -- meant as a fallback, not the
    default path. Returns None on any failure (missing/invalid key, no
    network, no confident match, fpcalc error) rather than raising, so
    callers can treat it exactly like an unsuccessful filename search."""
    if not api_key:
        return None

    acoustid.FPCALC_COMMAND = fpcalc_path()
    try:
        results = list(acoustid.match(api_key, str(path), timeout=timeout))
    except acoustid.NoBackendError:
        return None  # fpcalc missing/not executable -- fail closed, not crash
    except acoustid.FingerprintGenerationError:
        return None  # unreadable/corrupt audio file
    except acoustid.WebServiceError:
        return None  # bad API key, AcoustID down, rate-limited, etc.
    except Exception:
        return None

    if not results:
        return None

    # parse_lookup_result already sorts by score descending; take the best.
    score, _recording_id, title, artist = results[0]
    if not title or not artist:
        return None

    return MatchCandidate(
        score=round(score * 100),
        artist=artist,
        title=title,
        album=None,  # AcoustID's basic recording lookup doesn't include release/album info
        source="fingerprint",
    )


def best_match(
    path: Path,
    timeout: float = 10.0,
    known_artist: Optional[str] = None,
    known_title: Optional[str] = None,
) -> Optional[MatchCandidate]:
    """Search MusicBrainz first; if that finds nothing confident and an
    AcoustID key is configured, fall back to audio fingerprinting. Returns
    the best candidate found by either strategy (regardless of confidence --
    callers decide what to do with a low-confidence match, typically via
    MatchCandidate.is_confident).

    If the file already has a title tag (known_title), that's used as the
    search query -- when double-checking metadata that's already present,
    verifying against the *actual* existing tags is the point, and a
    filename guess can easily be worse than the tag itself. Falls back to
    guessing from the filename when there's no existing tag to go on."""
    if known_title:
        guessed = (known_artist or "", known_title)
    else:
        guessed = guess_query(path)
    filename_match = None
    if guessed is not None:
        artist, title = guessed
        candidates = search(artist, title, timeout=timeout)
        filename_match = candidates[0] if candidates else None

    if filename_match is not None and filename_match.is_confident:
        return filename_match

    api_key = settings.get_acoustid_api_key()
    fingerprint_result = fingerprint_match(path, api_key) if api_key else None

    if fingerprint_result is not None:
        return fingerprint_result
    return filename_match
