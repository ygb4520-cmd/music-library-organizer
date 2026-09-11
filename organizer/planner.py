"""Build the move plan from scanned tracks: destination paths, duplicate
detection, and destination-path conflict detection. Never touches disk."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from . import artist_utils, inference, settings
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
    tracks: List[TrackInfo], source_root: Path, destination_root: Path
) -> List[PlanItem]:
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

    _flag_duplicates(items)
    _flag_conflicts(items)

    return items


def _flag_duplicates(items: List[PlanItem]) -> None:
    groups: Dict[str, List[PlanItem]] = {}
    for item in items:
        if item.status == Status.NEEDS_REVIEW:
            continue
        title = item.track.title or item.track.path.stem
        artist = item.track.artist or item.track.album_artist or ""
        key = _normalize_key(f"{artist}|{title}")
        if not _normalize_key(title):
            continue
        groups.setdefault(key, []).append(item)

    group_num = 0
    for key, group_items in groups.items():
        if len(group_items) < 2:
            continue
        group_num += 1
        group_id = f"dup-{group_num}"
        for item in group_items:
            item.status = Status.DUPLICATE
            item.group_id = group_id
            item.include = False
            item.notes = (
                f"Possible duplicate of {len(group_items) - 1} other file(s) "
                f"with the same title/artist."
            )


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
