"""VideoDisplay: play a video file via mpv."""

from __future__ import annotations

import asyncio
from pathlib import Path

import mpv  # type: ignore[import-not-found]

from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext


class VideoDisplay(Displayable):
    """Plays a video file using python-mpv.

    mpv handles hardware-accelerated decode when the HAL profile sets
    hw_video_decode=True; software decode is used otherwise. The asyncio
    event loop yields control to mpv for the duration of the clip via an
    asyncio.Event, then resumes.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self, ctx: LoadContext) -> None:
        """No pre-load needed; mpv opens the file at play time."""

    async def display(self, ctx: DisplayContext) -> None:
        """Play the video and block until it finishes."""
        done = asyncio.Event()
        loop = asyncio.get_running_loop()

        player = ctx.mpv_player
        if player is None:
            player = mpv.MPV(
                vo="gpu",
                hwdec="auto" if _hw_decode_available(ctx) else "no",
                fullscreen=True,
            )

        def _on_end(_name: str, _value: object) -> None:
            loop.call_soon_threadsafe(done.set)

        player.observe_property("core-idle", _on_end)
        player.play(str(self._path))
        await done.wait()
        player.unobserve_property("core-idle", _on_end)


def _hw_decode_available(ctx: DisplayContext) -> bool:
    """Return True when the display context indicates HW decode is usable."""
    return getattr(ctx, "hw_video_decode", False)
