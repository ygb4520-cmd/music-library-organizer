"""Persistent app preferences via Qt's QSettings (platform-native storage:
a plist on macOS, the registry on Windows) -- no new dependency.

The AcoustID key stored here is a free, unauthenticated-rate-limited
identifier, not a password or payment credential, so plain QSettings
storage is appropriate (unlike, say, the Gemini API key in a sibling app,
which is stored in the OS keychain because it's a real per-user secret)."""
from __future__ import annotations

from PySide6.QtCore import QSettings

ORG = "ybrownstein"
APP = "MusicLibraryOrganizer"

SORT_CONFIDENCE_DESC = "confidence_desc"
SORT_CONFIDENCE_ASC = "confidence_asc"
SORT_AZ = "az"
SORT_OPTIONS = [SORT_CONFIDENCE_DESC, SORT_CONFIDENCE_ASC, SORT_AZ]
SORT_LABELS = {
    SORT_CONFIDENCE_DESC: "Confidence: High to Low",
    SORT_CONFIDENCE_ASC: "Confidence: Low to High",
    SORT_AZ: "A to Z",
}

MULTI_ARTIST_FULL = "full"
MULTI_ARTIST_MAIN_ONLY = "main_only"
MULTI_ARTIST_OPTIONS = [MULTI_ARTIST_FULL, MULTI_ARTIST_MAIN_ONLY]
MULTI_ARTIST_LABELS = {
    MULTI_ARTIST_FULL: "Keep full artist credit (e.g. \"A feat. B\")",
    MULTI_ARTIST_MAIN_ONLY: "Use main artist only (drop \"feat. ...\")",
}


def _settings() -> QSettings:
    return QSettings(ORG, APP)


def get_sort_order() -> str:
    value = _settings().value("sort_order", SORT_CONFIDENCE_DESC)
    return value if value in SORT_OPTIONS else SORT_CONFIDENCE_DESC


def set_sort_order(value: str) -> None:
    _settings().setValue("sort_order", value)


def get_multi_artist_mode() -> str:
    value = _settings().value("multi_artist_mode", MULTI_ARTIST_FULL)
    return value if value in MULTI_ARTIST_OPTIONS else MULTI_ARTIST_FULL


def set_multi_artist_mode(value: str) -> None:
    _settings().setValue("multi_artist_mode", value)


def get_acoustid_api_key() -> str:
    return _settings().value("acoustid_api_key", "") or ""


def set_acoustid_api_key(value: str) -> None:
    _settings().setValue("acoustid_api_key", value)
