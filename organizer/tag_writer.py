"""Writes artist/title/album/album_artist/track_number tags via mutagen's
"easy" interface, which covers MP3/ID3, FLAC, Ogg Vorbis/Opus, and MP4/M4A
with one consistent API.

This is the one place in the app that writes to audio files -- everywhere
else is strictly read-only by design (see README's "What it does and does
not do"). Only ever called after the user explicitly confirms: either a
specific match in the metadata-lookup preview dialog, or a manual edit in
the standalone tag editor. Never automatic.

Each field is None (leave untouched) or a string ("" explicitly clears the
field, matching what a user emptying a text box in the editor would expect
-- unlike an earlier version of this function, where a falsy value was
silently skipped, which meant there was no way to actually blank a field).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import mutagen

# mutagen's easy interface doesn't support WAV -- most WAV files don't
# carry a standardized tag scheme mutagen can reliably round-trip, same
# caveat already noted in tag_reader.py/README for reading.
UNSUPPORTED_WRITE_EXTENSIONS = {".wav"}


class TagWriteError(Exception):
    pass


def can_write_tags(ext: str) -> bool:
    return ext.lower() not in UNSUPPORTED_WRITE_EXTENSIONS


def write_tags(
    path: Path,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    album: Optional[str] = None,
    album_artist: Optional[str] = None,
    track_number: Optional[str] = None,
) -> None:
    ext = path.suffix.lower()
    if not can_write_tags(ext):
        raise TagWriteError(f"Writing tags to {ext} files isn't supported.")

    try:
        audio = mutagen.File(path, easy=True)
    except Exception as e:
        raise TagWriteError(f"Could not open file: {e}") from e

    if audio is None:
        raise TagWriteError("Unrecognized audio file format.")

    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception as e:
            raise TagWriteError(f"Could not create a tag container: {e}") from e

    fields = {
        "artist": artist,
        "title": title,
        "album": album,
        "albumartist": album_artist,
        "tracknumber": track_number,
    }
    for key, value in fields.items():
        if value is None:
            continue
        if value == "":
            # Clearing a field: mutagen's easy interface raises if you try
            # to delete a key that isn't present, so check first.
            if key in audio:
                del audio[key]
        else:
            audio[key] = value

    try:
        audio.save()
    except Exception as e:
        raise TagWriteError(f"Could not save tags: {e}") from e
