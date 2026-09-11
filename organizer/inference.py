"""Fallback inference of Album Artist / Album / Title from filename and folder
structure, used only when tag data is missing or incomplete.

This never touches tag data on disk -- it only fills in-memory fields on the
TrackInfo object used to compute a destination path.
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import MetadataSource, TrackInfo

# Ordered filename patterns, most specific first. All match against the file
# stem (no extension). Group names: artist, album, track, title.
_FILENAME_PATTERNS = [
    # Artist - Album - 01 - Title / Artist - Album - 01. Title / Artist - Album - 01 Title
    re.compile(
        r"^(?P<artist>.+?)\s*-\s*(?P<album>.+?)\s*-\s*(?P<track>\d{1,3})[\.\-\s]+(?P<title>.+)$"
    ),
    # Artist - 01 - Title  (no album in filename)
    re.compile(r"^(?P<artist>.+?)\s*-\s*(?P<track>\d{1,3})[\.\-\s]+(?P<title>.+)$"),
    # 01 - Title / 01. Title / 01 Title  (track + title only)
    re.compile(r"^(?P<track>\d{1,3})[\.\-\s]+(?P<title>.+)$"),
    # Artist - Title  (two-part, no track number)
    re.compile(r"^(?P<artist>.+?)\s*-\s*(?P<title>.+)$"),
]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -._")


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def _parse_filename(stem: str) -> dict:
    for pattern in _FILENAME_PATTERNS:
        match = pattern.match(stem)
        if not match:
            continue
        groups = match.groupdict()
        result = {}
        if groups.get("artist"):
            result["artist"] = _clean(groups["artist"])
        if groups.get("album"):
            result["album"] = _clean(groups["album"])
        if groups.get("title"):
            result["title"] = _clean(groups["title"])
        if groups.get("track"):
            result["track_number"] = groups["track"]
        if result.get("title"):
            return result
    return {}


def guess_from_filename(stem: str) -> dict:
    """Public wrapper around the same filename-pattern guessing used for
    folder-placement fallback, reused by metadata_lookup.py so both features
    parse filenames identically instead of duplicating the pattern list."""
    return _parse_filename(stem)


def apply_fallback(track: TrackInfo, source_root: Path) -> TrackInfo:
    """Fill missing artist/album/title fields on `track` using filename and
    folder heuristics. Never overwrites a value already present from tags."""
    inferred_anything = False
    had_complete_tags = bool(track.album_artist or track.artist) and bool(track.album)

    parsed = _parse_filename(track.path.stem)

    if not track.artist and parsed.get("artist"):
        track.artist = parsed["artist"]
        inferred_anything = True
    if not track.album and parsed.get("album"):
        track.album = parsed["album"]
        inferred_anything = True
    if not track.title and parsed.get("title"):
        track.title = parsed["title"]
        inferred_anything = True
    if not track.track_number and parsed.get("track_number"):
        track.track_number = parsed["track_number"]

    # Folder heuristic: assume Artist/Album/file.ext layout. Only use a
    # folder name as a stand-in when it isn't the scanned root itself
    # (the root is usually just "Music" or similarly uninformative).
    parent = track.path.parent
    grandparent = parent.parent

    if not track.album and parent != source_root:
        track.album = _clean(parent.name)
        inferred_anything = True

    if not track.artist and not track.album_artist:
        # Only trust the grandparent folder as artist if it's inside the
        # scanned tree (i.e. we actually walked through it as a subfolder),
        # not some ancestor of the source root itself.
        is_within = grandparent == source_root or _is_relative_to(grandparent, source_root)
        if is_within:
            track.artist = _clean(grandparent.name)
            inferred_anything = True

    if not track.album_artist and track.artist:
        track.album_artist = track.artist

    if had_complete_tags:
        track.metadata_source = MetadataSource.TAG
    elif track.album_artist and track.album:
        track.metadata_source = MetadataSource.INFERRED if inferred_anything else track.metadata_source
    else:
        track.metadata_source = MetadataSource.NONE

    return track


def needs_manual_review(track: TrackInfo) -> bool:
    return not (track.album_artist and track.album)
