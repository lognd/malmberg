"""Shared Pydantic models for malmberg_core."""

from __future__ import annotations

from malmberg_core.models.discovery import DiscoveryPayload
from malmberg_core.models.id import Tag
from malmberg_core.models.media import (
    HidePolicy,
    MediaItem,
    MediaMetadata,
    MediaPage,
)

__all__ = [
    "DiscoveryPayload",
    "HidePolicy",
    "MediaItem",
    "MediaMetadata",
    "MediaPage",
    "Tag",
]
