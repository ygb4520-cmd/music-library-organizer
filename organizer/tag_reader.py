"""Read-only audio tag extraction via mutagen.

Never writes to files. Reads are best-effort and format-agnostic: we try the
"easy" mutagen interface first (works for MP3/ID3, FLAC, Ogg Vorbis/Opus,
MP4/M4A) and fall back to probing known raw tag keys for formats/containers
where the easy interface doesn't exist or is missing a field.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import mutagen

from .models import MetadataSource, TrackInfo

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus"}

# Raw fallback keys to probe when the easy interface is unavailable/incomplete.
_ID3_RAW_KEYS = {
    "album_artist": ["TPE2"],
    "artist": ["TPE1"],
    "album": ["TALB"],
    "title": ["TIT2"],
    "track_number": ["TRCK"],
}
_VORBIS_RAW_KEYS = {
    "album_artist": ["albumartist", "album artist", "ALBUMARTIST"],
    "artist": ["artist", "ARTIST"],
    "album": ["album", "ALBUM"],
    "title": ["title", "TITLE"],
    "track_number": ["tracknumber", "TRACKNUMBER"],
}
_MP4_RAW_KEYS = {
    "album_artist": ["aART"],
    "artist": ["\xa9ART"],
    "album": ["\xa9alb"],
    "title": ["\xa9nam"],
    "track_number": ["trkn"],
}

_EASY_KEYS = {
    "album_artist": ["albumartist"],
    "artist": ["artist"],
    "album": ["album"],
    "title": ["title"],
    "track_number": ["tracknumber"],
}


def _first_str(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    if isinstance(value, tuple):  # e.g. MP4 track number tuples (n, total)
        value = value[0] if value else None
        if value is None:
            return None
    text = str(value).strip()
    return text or None


def _from_easy(path: Path) -> dict:
    result = {}
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:
        return result
    if audio is None or audio.tags is None:
        return result
    tags = audio.tags
    for field, keys in _EASY_KEYS.items():
        for key in keys:
            try:
                if key in tags:
                    val = _first_str(tags[key])
                    if val:
                        result[field] = val
                        break
            except Exception:
                continue
    return result


def _from_raw(path: Path, raw_key_map: dict) -> dict:
    result = {}
    try:
        audio = mutagen.File(path)
    except Exception:
        return result
    if audio is None or audio.tags is None:
        return result
    tags = audio.tags
    for field, keys in raw_key_map.items():
        for key in keys:
            try:
                if key in tags:
                    val = _first_str(tags[key])
                    if val:
                        result[field] = val
                        break
            except Exception:
                continue
    return result


def _raw_key_map_for(ext: str) -> dict:
    if ext == ".mp3":
        return _ID3_RAW_KEYS
    if ext in (".m4a", ".aac"):
        return _MP4_RAW_KEYS
    if ext in (".flac", ".ogg", ".oga", ".opus"):
        return _VORBIS_RAW_KEYS
    return {}


def _read_bitrate(path: Path) -> Optional[int]:
    try:
        audio = mutagen.File(path)
        if audio is not None and getattr(audio, "info", None) is not None:
            return getattr(audio.info, "bitrate", None)
    except Exception:
        pass
    return None


def read_tags(path: Path) -> TrackInfo:
    ext = path.suffix.lower()
    size = 0
    try:
        size = path.stat().st_size
    except OSError:
        pass

    track = TrackInfo(path=path, ext=ext, size=size)

    try:
        merged = _from_easy(path)
        missing = [f for f in _EASY_KEYS if f not in merged]
        if missing:
            raw = _from_raw(path, _raw_key_map_for(ext))
            for f in missing:
                if f in raw:
                    merged[f] = raw[f]

        track.album_artist = merged.get("album_artist")
        track.artist = merged.get("artist")
        track.album = merged.get("album")
        track.title = merged.get("title")
        track.track_number = merged.get("track_number")
        track.bitrate = _read_bitrate(path)

        if track.album_artist or track.artist or track.album or track.title:
            track.metadata_source = MetadataSource.TAG
        else:
            track.metadata_source = MetadataSource.NONE
    except Exception as exc:  # never let a bad file crash the scan
        track.read_error = str(exc)
        track.metadata_source = MetadataSource.NONE

    return track
