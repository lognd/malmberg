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
        loop = asyncio.get_running_loop()

        player = ctx.mpv_player
        own_player = player is None
        if player is None:
            player = mpv.MPV(
                vo="gpu",
                hwdec="auto" if _hw_decode_available(ctx) else "no",
                fullscreen=True,
            )

        try:
            player.play(str(self._path))
            # wait_for_playback blocks until the clip ends; run it off the loop
            # rather than observing core-idle, which fires immediately while idle.
            await loop.run_in_executor(None, player.wait_for_playback)
        finally:
            if own_player:
                player.terminate()


def _hw_decode_available(ctx: DisplayContext) -> bool:
    """Return True when the display context indicates HW decode is usable."""
    return getattr(ctx, "hw_video_decode", False)
