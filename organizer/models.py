"""Data models shared across the scan -> plan -> move pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class MetadataSource(str, Enum):
    TAG = "tag"
    INFERRED = "inferred"
    NONE = "none"


class Status(str, Enum):
    READY = "ready"              # clean tags, no conflicts
    INFERRED = "inferred"        # filename/folder fallback filled in artist/album
    DUPLICATE = "duplicate"      # same (title, artist) as another file
    CONFLICT = "conflict"        # destination path collides with another file
    NEEDS_REVIEW = "needs_review"  # could not resolve album artist/album at all


@dataclass
class TrackInfo:
    path: Path
    ext: str
    album_artist: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    track_number: Optional[str] = None
    bitrate: Optional[int] = None
    size: int = 0
    metadata_source: MetadataSource = MetadataSource.NONE
    read_error: Optional[str] = None

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def display_title(self) -> str:
        return self.title or self.path.stem


@dataclass
class PlanItem:
    track: TrackInfo
    dest_path: Optional[Path] = None
    status: Status = Status.READY
    group_id: Optional[str] = None
    include: bool = True
    notes: str = ""
    move_error: Optional[str] = None

    @property
    def source_path(self) -> Path:
        return self.track.path
