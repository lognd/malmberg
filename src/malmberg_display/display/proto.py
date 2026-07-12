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
    geocoder: Optional[Any] = None
    """Optional (lat, lon) -> str callable for reverse-geocoding GPS coordinates."""


class DisplayContext(BaseModel):
    """Resources shared across all display() calls (initialized once at startup).

    The actual pygame surface and mpv instance are stored as opaque `Any` so
    that display.py can import without requiring pygame/mpv at import time.
    """

    model_config = {"arbitrary_types_allowed": True}

    screen: Optional[Any] = None
    """pygame.Surface or None if not yet initialized."""
    base_frame: Optional[Any] = None
    """Copy of the last fully-rendered frame (image + overlay), for the toast
    task to repaint over without re-decoding the current item."""
    skip_event: Optional[Any] = None
    """asyncio.Event set to cut the current item's dwell short (Next / producer
    switch); the renderer waits on it instead of a plain sleep."""
    rendering: bool = False
    """True while the picture renderer is actively drawing/cross-fading; the
    toast task must not touch the screen during this window (avoids tearing)."""
    mpv_player: Optional[Any] = None
    """mpv.MPV instance or None if not yet initialized."""
    overlay_renderer: Optional[Any] = None
    """OverlayRenderer instance or None to disable overlays."""
    width: int = 1920
    height: int = 1080
    fade_duration_s: float = 0.5
    """Cross-fade duration between items."""
    dwell_s: float = 10.0
    """Default time to display each image."""
    show_clock: bool = True
    """Render the current-time clock overlay."""
    show_caption: bool = True
    """Render the per-image date/location/camera caption overlay."""
    mute_video: bool = True
    """Mute video audio by default; the API unmutes only when the user manually
    shows a single item (so the ambient slideshow never plays sound)."""
    hw_video_decode: bool = False
    """Whether mpv may use hardware decoding (from the HAL profile).

    This was never populated, so mpv always ran with hwdec=no -- software
    decoding video on a Pi, which is why playback was choppy.
    """
    video_max_s: float = 600.0
    """Give up on a clip after this long (0 disables).

    Guards against a video that stalls forever in mpv: without a cap the
    display task blocks on it and the whole frame freezes.
    """


class Displayable(ABC):
    """A single renderable media item (image, video, or web overlay)."""

    @abstractmethod
    async def load(self, ctx: LoadContext) -> None:
        """Pre-load / decode the item so display() can render without I/O delay."""

    @abstractmethod
    async def display(self, ctx: DisplayContext) -> None:
        """Render the item to the display and block until the dwell time expires."""
