"""Build the move plan from scanned tracks: destination paths, duplicate
detection, and destination-path conflict detection. Never touches disk."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import artist_utils, inference, metadata_lookup, settings
from .models import MetadataSource, PlanItem, Status, TrackInfo

_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_component(name: str) -> str:
    cleaned = _INVALID_WIN_CHARS.sub("_", name).strip()
    cleaned = cleaned.rstrip(" .")  # Windows disallows trailing dot/space
    return cleaned or "Unknown"


def _normalize_key(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def build_plan(
    tracks: List[TrackInfo],
    source_root: Path,
    destination_root: Path,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> List[PlanItem]:
    """`is_cancelled`, if given, is polled during the (potentially slow,
    network-bound) fingerprint duplicate-detection pass so a scan cancel
    takes effect promptly instead of only after every file's been
    fingerprinted -- the rest of this function is pure/fast enough not to
    need it."""
    items: List[PlanItem] = []
    main_artist_only = settings.get_multi_artist_mode() == settings.MULTI_ARTIST_MAIN_ONLY

    for track in tracks:
        if inference.needs_manual_review(track):
            items.append(
                PlanItem(
                    track=track,
                    dest_path=None,
                    status=Status.NEEDS_REVIEW,
                    include=False,
                    notes="Could not determine Album Artist and Album from tags, filename, or folder.",
                )
            )
            continue

        folder_artist = track.album_artist
        if main_artist_only:
            # Same Settings preference the metadata-lookup preview uses --
            # applies here too so folder names are consistent with it,
            # e.g. "Drake feat. Rihanna" -> the "Drake" folder, not a
            # separate one per featured-artist combination.
            folder_artist = artist_utils.main_artist(folder_artist)

        album_artist = sanitize_component(folder_artist)
        album = sanitize_component(track.album)
        dest_path = destination_root / album_artist / album / track.filename

        status = Status.READY if track.metadata_source == MetadataSource.TAG else Status.INFERRED
        items.append(PlanItem(track=track, dest_path=dest_path, status=status, include=True))

    _flag_duplicates(items, is_cancelled)
    _flag_conflicts(items)

    return items


def _flag_duplicates(items: List[PlanItem], is_cancelled: Optional[Callable[[], bool]] = None) -> None:
    candidates = [item for item in items if item.status != Status.NEEDS_REVIEW]

    group_num = 0
    group_num = _group_by_fingerprint(candidates, group_num, is_cancelled)
    remaining = [item for item in candidates if item.status != Status.DUPLICATE]
    group_num = _group_by_key(
        remaining,
        group_num,
        method="tag",
        key_fn=lambda item: _normalize_key(
            f"{item.track.artist or item.track.album_artist or ''}|{item.track.title or item.track.path.stem}"
        ),
        skip_fn=lambda item: not _normalize_key(item.track.title or item.track.path.stem),
        note="Possible duplicate of {n} other file(s) with the same title/artist.",
    )
    remaining = [item for item in remaining if item.status != Status.DUPLICATE]
    _group_by_key(
        remaining,
        group_num,
        method="filename",
        key_fn=lambda item: _normalize_filename_key(item.track.path.stem),
        skip_fn=lambda item: not _normalize_filename_key(item.track.path.stem),
        note="Possible duplicate of {n} other file(s) with a matching filename.",
    )


def _normalize_filename_key(stem: str) -> str:
    """Strips a leading track-number prefix (same shape inference.py's
    filename patterns look for, e.g. "01 - ", "03.") before normalizing, so
    "01 - Song.mp3" and "07 Song.flac" are recognized as the same filename."""
    stem = re.sub(r"^\d{1,3}[\.\-\s]+", "", stem)
    return _normalize_key(stem)


def _group_by_key(
    items: List[PlanItem],
    group_num: int,
    method: str,
    key_fn: Callable[[PlanItem], str],
    skip_fn: Callable[[PlanItem], bool],
    note: str,
) -> int:
    groups: Dict[str, List[PlanItem]] = {}
    for item in items:
        if skip_fn(item):
            continue
        groups.setdefault(key_fn(item), []).append(item)

    for group_items in groups.values():
        if len(group_items) < 2:
            continue
        group_num += 1
        group_id = f"dup-{group_num}"
        for item in group_items:
            item.status = Status.DUPLICATE
            item.group_id = group_id
            item.include = False
            item.dup_method = method
            item.notes = note.format(n=len(group_items) - 1)
    return group_num


def _group_by_fingerprint(
    items: List[PlanItem], group_num: int, is_cancelled: Optional[Callable[[], bool]] = None
) -> int:
    """Highest-priority duplicate tier: identifies each track's actual audio
    content via the existing AcoustID/chromaprint integration (same
    fingerprint_match() the opt-in metadata-lookup feature uses) and groups
    tracks that resolve to the same recording -- catches duplicates filename
    and tag matching miss (re-encoded copies, differently-tagged rips of the
    same song, etc). Opt-in and best-effort: silently skipped whenever no
    AcoustID API key is configured or the bundled fpcalc binary isn't
    available, so libraries with neither behave exactly as before this
    feature existed. Reading + fingerprinting every candidate file is real
    per-scan I/O and network cost, which is why this stays gated behind the
    same key setup as the existing opt-in lookup feature rather than always
    running."""
    api_key = settings.get_acoustid_api_key()
    if not api_key or not Path(metadata_lookup.fpcalc_path()).exists():
        return group_num

    groups: Dict[str, List[PlanItem]] = {}
    for item in items:
        if is_cancelled is not None and is_cancelled():
            break
        match = metadata_lookup.fingerprint_match(item.track.path, api_key)
        if match is None or not match.is_confident:
            continue
        key = _normalize_key(f"{match.artist}|{match.title}")
        groups.setdefault(key, []).append(item)

    for group_items in groups.values():
        if len(group_items) < 2:
            continue
        group_num += 1
        group_id = f"dup-{group_num}"
        for item in group_items:
            item.status = Status.DUPLICATE
            item.group_id = group_id
            item.include = False
            item.dup_method = "fingerprint"
            item.notes = (
                f"Possible duplicate of {len(group_items) - 1} other file(s) -- "
                "identified as the same recording by audio fingerprint."
            )
    return group_num


def _flag_conflicts(items: List[PlanItem]) -> None:
    by_dest: Dict[Path, List[PlanItem]] = {}
    for item in items:
        if item.dest_path is None:
            continue
        by_dest.setdefault(item.dest_path, []).append(item)

    group_num = 0
    for dest, group_items in by_dest.items():
        if len(group_items) < 2:
            continue
        group_num += 1
        group_id = f"conflict-{group_num}"
        for item in group_items:
            item.status = Status.CONFLICT
            item.group_id = group_id
            item.include = False
            item.notes = (
                f"{len(group_items)} files would all move to the same destination path: {dest}"
            )
