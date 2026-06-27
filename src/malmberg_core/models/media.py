"""MediaItem and related models shared between server and display."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

HidePolicy = Literal["delete", "keep"]


class MediaMetadata(BaseModel):
    """EXIF and ingest metadata stored alongside each media file."""

    taken_at: Optional[datetime] = None
    """DateTimeOriginal from EXIF, if present; otherwise None."""
    ingest_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """When the file was received by the Server."""
    camera_model: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_s: Optional[float] = None
    """Duration in seconds for video files; None for images."""
    sha256: str = ""
    """SHA-256 hex digest of the original file."""


class MediaItem(BaseModel):
    """A single photo or video stored on the Server."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: Literal["image", "video"]
    filename: str
    server_path: str
    """Relative path from /fs/media/, e.g. '2024/06/15/IMG_0001.jpg'."""
    meta: MediaMetadata = Field(default_factory=MediaMetadata)
    do_not_display: bool = False
    hide_policy: HidePolicy = "delete"
    dwell_override_s: Optional[float] = None
    """Per-file dwell time override; None means use the global default."""
    tags: list[str] = Field(default_factory=list)


class MediaPage(BaseModel):
    """Paginated response for GET /media."""

    items: list[MediaItem]
    total: int
    page: int
    page_size: int
    has_next: bool
