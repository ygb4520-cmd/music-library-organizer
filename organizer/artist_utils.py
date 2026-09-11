"""Parses out a "main artist" from a full artist credit, for the optional
"use main artist only" mode.

Deliberately narrow: only strips an explicit "feat./ft./featuring X" suffix.
It does NOT split on "&", ",", "/", or "x" -- those are too often part of a
single act's actual name (e.g. "Earth, Wind & Fire", "Simon & Garfunkel",
"AC/DC") to safely treat as separators. A broader split would silently
mangle real single-artist names, which is worse than only handling the
unambiguous "featuring" case.
"""
from __future__ import annotations

import re

_FEATURING_RE = re.compile(r"\s+(?:feat\.?|featuring|ft\.?)\s+.+$", re.IGNORECASE)


def has_featured_artist(full_artist: str) -> bool:
    return bool(full_artist and _FEATURING_RE.search(full_artist))


def main_artist(full_artist: str) -> str:
    if not full_artist:
        return full_artist
    return _FEATURING_RE.sub("", full_artist).strip()
