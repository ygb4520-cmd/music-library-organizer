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

import enum
import json
import logging
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import acoustid

from . import inference, settings


logger = logging.getLogger(__name__)

MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
# MusicBrainz's usage policy requires a descriptive User-Agent identifying
# the application; requests without one are more likely to be rate-limited
# or blocked. No API key needed for this level of usage.
USER_AGENT = "MusicLibraryOrganizer/0.1 (personal-use desktop app)"
# MusicBrainz asks for at most ~1 request/second for unauthenticated use.
MIN_SECONDS_BETWEEN_REQUESTS = 1.1
# AcoustID allows at most 3 requests/second per application.
MIN_SECONDS_BETWEEN_ACOUSTID_REQUESTS = 0.35
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


class LookupStatus(enum.Enum):
    """Why a lookup did or didn't produce a result, so the UI can tell "not in the database" apart from a real problem."""
    OK = "ok"
    NO_MATCH = "no match"
    NO_API_KEY = "no AcoustID API key"
    FPCALC_MISSING = "fpcalc not found"
    BAD_KEY = "AcoustID API key rejected"
    CORRUPT_AUDIO = "audio could not be fingerprinted"
    NETWORK_ERROR = "network error"
    RATE_LIMITED = "rate limited / service busy"
    UNKNOWN_ERROR = "unexpected error"


_STATUS_HELP = {
    LookupStatus.OK: "Match found.",
    LookupStatus.NO_MATCH: "NO_MATCH: the song was not found in the database.",
    LookupStatus.NO_API_KEY: "NO_API_KEY: no AcoustID API key is set (Settings).",
    LookupStatus.FPCALC_MISSING: "FPCALC_MISSING: the fpcalc helper is missing or could not be run.",
    LookupStatus.BAD_KEY: "BAD_KEY: AcoustID rejected the API key (wrong or expired).",
    LookupStatus.CORRUPT_AUDIO: "CORRUPT_AUDIO: fpcalc could not read this audio file (corrupt or unsupported).",
    LookupStatus.NETWORK_ERROR: "NETWORK_ERROR: could not reach the lookup service (network problem or timeout).",
    LookupStatus.RATE_LIMITED: "RATE_LIMITED: the lookup service is rate-limiting or temporarily down.",
    LookupStatus.UNKNOWN_ERROR: "UNKNOWN_ERROR: unexpected failure (see the log for details).",
}


@dataclass
class LookupResult:
    """Candidates plus the reason there are (or aren't) any. `detail` is the underlying error text, if any."""
    candidates: List["MatchCandidate"] = field(default_factory=list)
    status: LookupStatus = LookupStatus.NO_MATCH
    detail: str = ""

    @property
    def message(self) -> str:
        text = _STATUS_HELP[self.status]
        return f"{text} ({self.detail})" if self.detail and self.status is not LookupStatus.NO_MATCH else text


class RateLimiter:
    """Thread-safe pacing: wait() blocks until at least `interval` seconds have
    passed since the previous caller was released. Lets many worker threads
    share one server-side rate limit while doing everything else in parallel."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


_musicbrainz_limiter = RateLimiter(MIN_SECONDS_BETWEEN_REQUESTS)
_acoustid_limiter = RateLimiter(MIN_SECONDS_BETWEEN_ACOUSTID_REQUESTS)


def guess_query(path: Path) -> Optional[tuple[str, str]]:
    """Returns (artist, title) guessed from the filename, or None if the
    filename doesn't contain enough to search with (no title at all)."""
    guessed = inference.guess_from_filename(path.stem)
    title = guessed.get("title")
    if not title:
        return None
    return guessed.get("artist") or "", title


def _musicbrainz_error_status(exc: BaseException) -> LookupStatus:
    # MusicBrainz answers 503 (and sometimes 429) when it is rate-limiting or overloaded.
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (429, 503):
        return LookupStatus.RATE_LIMITED
    return LookupStatus.NETWORK_ERROR


def search_with_status(artist: str, title: str, timeout: float = 10.0) -> LookupResult:
    """Queries MusicBrainz for recordings matching artist+title. Candidates are sorted by score (highest first);
    `status` says why the list is empty when it is (NO_MATCH vs. a network/rate-limit problem). Never raises for
    network or parsing problems."""
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
        _musicbrainz_limiter.wait()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
            break
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            # OSError covers socket.timeout too -- on Python <3.10 that's a
            # distinct exception from TimeoutError, not a subclass of it, so
            # catching only TimeoutError silently missed real network timeouts.
            logger.warning("MusicBrainz search failed (attempt %d/2) for %r: %s", attempt + 1, query, exc, exc_info=True)
            if attempt == 0:
                time.sleep(2.0)
                continue
            return LookupResult([], _musicbrainz_error_status(exc), str(exc))

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
    return LookupResult(candidates, LookupStatus.OK if candidates else LookupStatus.NO_MATCH)


def search(artist: str, title: str, timeout: float = 10.0) -> list[MatchCandidate]:
    """Like search_with_status() but returns just the candidates (possibly empty)."""
    return search_with_status(artist, title, timeout=timeout).candidates


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


# -- Running fpcalc ------------------------------------------------------------------------------------------------

FPCALC_MAX_SECONDS_OF_AUDIO = 120  # same default pyacoustid uses
FPCALC_TIMEOUT = 120.0


class FpcalcMissingError(Exception):
    """fpcalc isn't there or can't be started."""


class FpcalcFailedError(Exception):
    """fpcalc ran but couldn't produce a fingerprint (corrupt/unsupported audio, bad output)."""


def hidden_window_popen_kwargs(platform: str = sys.platform) -> dict:
    """Extra Popen arguments that keep a helper process from flashing a console window. Windows only (a windowed app
    has no console of its own, so each fpcalc.exe run would otherwise pop one up); empty on other platforms."""
    if platform != "win32":
        return {}
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    if hasattr(subprocess, "STARTUPINFO"):
        info = subprocess.STARTUPINFO()
        info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        info.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = info
    return kwargs


def parse_fpcalc_output(output: bytes) -> tuple[float, bytes]:
    """(duration, fingerprint) from fpcalc's `KEY=value` lines. Raises FpcalcFailedError if either is missing/bad."""
    duration = fp = None
    for line in output.splitlines():
        key, sep, value = line.partition(b"=")
        if not sep:
            continue
        if key == b"DURATION":
            try:
                duration = float(value)
            except ValueError:
                raise FpcalcFailedError("fpcalc duration not numeric")
        elif key == b"FINGERPRINT":
            fp = value.strip()
    if duration is None or not fp:
        raise FpcalcFailedError("missing fpcalc output")
    return duration, fp


def run_fpcalc(path, fpcalc: Optional[str] = None, platform: str = sys.platform, popen=subprocess.Popen) -> tuple[float, bytes]:
    """Fingerprints one file with the bundled fpcalc, started without a console window on Windows. Returns
    (duration, fingerprint) ready for acoustid.lookup(). Our own small runner instead of acoustid.fingerprint_file(),
    so nothing inside the third-party library has to be patched."""
    fpcalc = fpcalc or fpcalc_path()
    command = [fpcalc, "-length", str(FPCALC_MAX_SECONDS_OF_AUDIO), str(path)]
    try:
        proc = popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **hidden_window_popen_kwargs(platform))
    except OSError as exc:
        raise FpcalcMissingError(f"fpcalc could not be started ({fpcalc}): {exc}") from exc
    try:
        output, _ = proc.communicate(timeout=FPCALC_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise FpcalcFailedError("fpcalc timed out")
    if proc.returncode:
        raise FpcalcFailedError(f"fpcalc exited with status {proc.returncode}")
    return parse_fpcalc_output(output)


_RATE_LIMIT_RE = re.compile(r"rate[ -]?limit|too many requests|\b429\b|\b503\b", re.IGNORECASE)


def _looks_rate_limited(text: str) -> bool:
    return bool(_RATE_LIMIT_RE.search(text or ""))


# AcoustID web-service error codes (https://acoustid.org/webservice#errors).
_ACOUSTID_BAD_KEY_CODES = {4, 12}
_ACOUSTID_RATE_LIMIT_CODES = {14}


def _acoustid_error_status(response) -> Optional[tuple[LookupStatus, str]]:
    """If the AcoustID response is an error payload, returns (status, message); otherwise None."""
    if not isinstance(response, dict) or response.get("status") == "ok":
        return None
    error = response.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    message = (error.get("message") if isinstance(error, dict) else None) or f"status: {response.get('status')}"
    lowered = str(message).lower()
    if code in _ACOUSTID_BAD_KEY_CODES or "api key" in lowered:
        return LookupStatus.BAD_KEY, str(message)
    if code in _ACOUSTID_RATE_LIMIT_CODES or _looks_rate_limited(lowered):
        return LookupStatus.RATE_LIMITED, str(message)
    return LookupStatus.UNKNOWN_ERROR, str(message)


def fingerprint_lookup(path: Path, api_key: str, timeout: float = 30.0, limit: int = 5) -> LookupResult:
    """All AcoustID matches for a track's audio (best first, duplicates removed), with a status explaining an empty
    result. Never raises and never writes anything (fail closed); the full exception is logged."""
    if not api_key:
        return LookupResult([], LookupStatus.NO_API_KEY)

    try:
        # Same steps as acoustid.match(), split so the slow local fpcalc run
        # happens in parallel across threads and only the web request is paced.
        duration, fp = run_fpcalc(path)
        _acoustid_limiter.wait()
        response = acoustid.lookup(api_key, fp, duration, timeout=timeout)
        problem = _acoustid_error_status(response)
        if problem is not None:
            logger.warning("AcoustID rejected the lookup for %s: %s (%s)", path, problem[1], problem[0].name)
            return LookupResult([], problem[0], problem[1])
        results = list(acoustid.parse_lookup_result(response))
    except FpcalcMissingError as exc:
        logger.error("fpcalc unavailable for %s: %s", path, exc, exc_info=True)
        return LookupResult([], LookupStatus.FPCALC_MISSING, str(exc))
    except FpcalcFailedError as exc:
        logger.warning("fpcalc could not fingerprint %s: %s", path, exc, exc_info=True)
        return LookupResult([], LookupStatus.CORRUPT_AUDIO, str(exc))
    except acoustid.WebServiceError as exc:
        logger.warning("AcoustID web request failed for %s: %s", path, exc, exc_info=True)
        message = str(exc)
        status = LookupStatus.NETWORK_ERROR
        if _looks_rate_limited(message):
            status = LookupStatus.RATE_LIMITED
        return LookupResult([], status, message)
    except (OSError, TimeoutError) as exc:
        logger.warning("Network/OS error during AcoustID lookup for %s: %s", path, exc, exc_info=True)
        return LookupResult([], LookupStatus.NETWORK_ERROR, str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during AcoustID lookup for %s", path)
        return LookupResult([], LookupStatus.UNKNOWN_ERROR, str(exc))

    candidates: list[MatchCandidate] = []
    seen = set()
    # parse_lookup_result already sorts by score descending.
    for score, _recording_id, title, artist in results:
        if not title or not artist:
            continue
        key = (artist.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            MatchCandidate(
                score=round(score * 100),
                artist=artist,
                title=title,
                album=None,  # AcoustID's basic recording lookup doesn't include release/album info
                source="fingerprint",
            )
        )
        if len(candidates) >= limit:
            break
    return LookupResult(candidates, LookupStatus.OK if candidates else LookupStatus.NO_MATCH)


def fingerprint_candidates(path: Path, api_key: str, timeout: float = 30.0, limit: int = 5) -> list[MatchCandidate]:
    """All AcoustID matches for a track's audio (best first, duplicates removed). Returns [] on any failure rather
    than raising; use fingerprint_lookup() to learn why."""
    return fingerprint_lookup(path, api_key, timeout=timeout, limit=limit).candidates


def fingerprint_match(path: Path, api_key: str, timeout: float = 30.0) -> Optional[MatchCandidate]:
    """Identifies a track from its actual audio content via AcoustID,
    regardless of filename. Slower than the filename search (has to read
    the audio to compute a fingerprint). Returns None on any failure so
    callers can treat it exactly like an unsuccessful filename search."""
    found = fingerprint_candidates(path, api_key, timeout=timeout, limit=1)
    return found[0] if found else None


def alternatives(
    path: Path,
    rejected=(),
    known_artist: Optional[str] = None,
    known_title: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 10.0,
) -> list[MatchCandidate]:
    """Other possible matches for a track after the user marked a match as wrong. Gathers MusicBrainz filename
    results plus AcoustID fingerprint results (when a key is set), and leaves out anything in `rejected`
    (an iterable of (artist, title) pairs that the user already said were wrong). Best score first."""
    bad = {(a.strip().lower(), t.strip().lower()) for a, t in rejected}
    found: list[MatchCandidate] = []
    guessed = (known_artist or "", known_title) if known_title else guess_query(path)
    if guessed is not None:
        found.extend(search(guessed[0], guessed[1], timeout=timeout))
    if api_key is None:
        api_key = settings.get_acoustid_api_key()
    if api_key:
        found.extend(fingerprint_candidates(path, api_key))

    out: list[MatchCandidate] = []
    seen = set()
    for c in sorted(found, key=lambda c: c.score, reverse=True):
        key = (c.artist.strip().lower(), c.title.strip().lower())
        if key in bad or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def best_match_with_status(
    path: Path,
    timeout: float = 10.0,
    known_artist: Optional[str] = None,
    known_title: Optional[str] = None,
    api_key: Optional[str] = None,
    fingerprint_only: bool = False,
) -> tuple[Optional[MatchCandidate], LookupResult]:
    """Like best_match(), but also returns a LookupResult explaining the outcome. When a candidate is returned the
    status is OK; otherwise it says why there is none (NO_MATCH only when the lookup really ran and found nothing)."""
    if fingerprint_only:
        if api_key is None:
            api_key = settings.get_acoustid_api_key()
        result = fingerprint_lookup(path, api_key or "", timeout=30.0, limit=1)
        match = result.candidates[0] if result.candidates else None
        return match, result

    if known_title:
        guessed = (known_artist or "", known_title)
    else:
        guessed = guess_query(path)
    filename_match = None
    filename_result = LookupResult([], LookupStatus.NO_MATCH, "no usable title to search for" if guessed is None else "")
    if guessed is not None:
        artist, title = guessed
        filename_result = search_with_status(artist, title, timeout=timeout)
        filename_match = filename_result.candidates[0] if filename_result.candidates else None

    if filename_match is not None and filename_match.is_confident:
        return filename_match, filename_result

    if api_key is None:
        api_key = settings.get_acoustid_api_key()
    fingerprint_result = fingerprint_lookup(path, api_key, timeout=30.0, limit=1) if api_key else None

    if fingerprint_result is not None and fingerprint_result.candidates:
        return fingerprint_result.candidates[0], fingerprint_result
    if filename_match is not None:
        return filename_match, filename_result
    # Nothing found: report a real problem in preference to a plain "not found".
    for result in (fingerprint_result, filename_result):
        if result is not None and result.status not in (LookupStatus.NO_MATCH, LookupStatus.OK):
            return None, result
    return None, filename_result if fingerprint_result is None else fingerprint_result


def best_match(
    path: Path,
    timeout: float = 10.0,
    known_artist: Optional[str] = None,
    known_title: Optional[str] = None,
    api_key: Optional[str] = None,
    fingerprint_only: bool = False,
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
    guessing from the filename when there's no existing tag to go on.

    With fingerprint_only=True the filename search is skipped entirely and only the audio fingerprint is used
    (returns None when no AcoustID key is set). Use best_match_with_status() to also learn why nothing was found."""
    return best_match_with_status(
        path, timeout=timeout, known_artist=known_artist, known_title=known_title,
        api_key=api_key, fingerprint_only=fingerprint_only,
    )[0]
