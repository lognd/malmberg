"""VideoDisplay: play a video file via mpv, inside the frame's own window."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from malmberg_core.logging import get_logger
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext

_log = get_logger(__name__)


def make_player(wid: Optional[int], hw_decode: bool) -> Optional[Any]:
    """Create the one long-lived mpv player, drawing into the frame's window.

    *wid* is the X11 window id of the pygame window.  Embedding via ``wid``
    means mpv renders INTO the existing fullscreen window rather than opening
    one of its own.  Previously every clip spun up a fresh fullscreen mpv
    window and destroyed it afterwards; while that window came and went the
    desktop showed through, which is why the frame visibly cut to the desktop
    around videos.  Creating and tearing down mpv per clip also made playback
    stutter.

    Returns None if mpv is unavailable or no window id was given (headless);
    videos are then skipped rather than opening a stray window.
    """
    if wid is None:
        _log.warning("No window id for mpv; videos will be skipped")
        return None
    try:
        import mpv  # noqa: PLC0415 -- hardware-optional import deferred to runtime

        player = mpv.MPV(
            wid=str(wid),
            vo="gpu",
            hwdec="auto" if hw_decode else "no",
            idle="yes",  # stay alive between clips instead of exiting
            osc=False,
            input_default_bindings=False,
            keep_open="no",
        )
    except Exception as exc:  # mpv missing, libmpv too old, no GPU vo, ...
        _log.error("Could not start mpv (videos will be skipped): %s", exc)
        return None
    _log.info("mpv ready (embedded, hwdec=%s)", "auto" if hw_decode else "no")
    return player


def _stop(player: Any) -> None:
    """Stop playback without tearing the player down."""
    try:
        player.command("stop")
    except Exception:  # already stopped / shutting down
        pass


class VideoDisplay(Displayable):
    """Plays a video file on the shared, embedded mpv player.

    The player is created once at startup (see ``make_player``) and reused for
    every clip, so nothing opens or closes a window mid-slideshow.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self, ctx: LoadContext) -> None:
        """No pre-load needed; mpv opens the file at play time."""

    async def display(self, ctx: DisplayContext) -> None:
        """Play the clip, giving up rather than hanging the frame forever."""
        player = ctx.mpv_player
        if player is None:
            _log.warning("No mpv player; skipping video %s", self._path.name)
            return

        loop = asyncio.get_running_loop()
        timeout = ctx.video_max_s if ctx.video_max_s and ctx.video_max_s > 0 else None
        try:
            # Muted unless the user manually picked this one item to show, so
            # the ambient slideshow never plays sound on its own.
            player.mute = ctx.mute_video
            player.play(str(self._path))
            await asyncio.wait_for(
                loop.run_in_executor(None, player.wait_for_playback),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # A stalled clip used to block the display task forever. Stop it
            # (which also unblocks the waiting executor thread) and move on --
            # the queued photos keep flowing.
            _log.warning(
                "Video %s exceeded %.0fs; stopping and moving on",
                self._path.name,
                ctx.video_max_s,
            )
            _stop(player)
        except Exception as exc:
            _log.warning("Video %s failed to play (%s); skipping", self._path.name, exc)
            _stop(player)
