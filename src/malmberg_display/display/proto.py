"""Displayable protocol and shared rendering contexts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel


class LoadContext(BaseModel):
    """Resources shared across all load() calls (initialized once at startup)."""

    model_config = {"arbitrary_types_allowed": True}

    cache_dir: Path = Path("/tmp/malmberg-cache")
    """Directory for caching downloaded or transcoded media."""


class DisplayContext(BaseModel):
    """Resources shared across all display() calls (initialized once at startup).

    The actual pygame surface and mpv instance are stored as opaque `Any` so
    that display.py can import without requiring pygame/mpv at import time.
    """

    model_config = {"arbitrary_types_allowed": True}

    screen: Optional[Any] = None
    """pygame.Surface or None if not yet initialized."""
    mpv_player: Optional[Any] = None
    """mpv.MPV instance or None if not yet initialized."""
    width: int = 1920
    height: int = 1080
    fade_duration_s: float = 0.5
    """Cross-fade duration between items."""
    dwell_s: float = 10.0
    """Default time to display each image."""


class Displayable(ABC):
    """A single renderable media item (image, video, or web overlay)."""

    @abstractmethod
    async def load(self, ctx: LoadContext) -> None:
        """Pre-load / decode the item so display() can render without I/O delay."""

    @abstractmethod
    async def display(self, ctx: DisplayContext) -> None:
        """Render the item to the display and block until the dwell time expires."""
