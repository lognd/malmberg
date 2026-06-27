"""PictureDisplay: still image renderer with cross-fade and on-screen overlay."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pygame  # type: ignore[import-not-found]
from PIL import Image  # type: ignore[import-not-found]

from malmberg_display.display.overlay import ImageCaption
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext


class PictureDisplay(Displayable):
    """Displays a single image file with an optional metadata overlay.

    load() decodes the file with Pillow and converts it to a pygame Surface.
    display() cross-fades from the current screen content, then renders
    the clock and caption overlay on top.

    Parameters
    ----------
    path:
        Path to the image file.
    taken_at:
        EXIF date/time the photo was taken; shown in the caption overlay.
    lat, lon:
        GPS coordinates for reverse-geocoding; shown in the caption overlay.
    camera_model:
        EXIF camera model string; shown in the caption overlay.
    dwell_override_s:
        Per-image dwell time override; None means use ``DisplayContext.dwell_s``.
    """

    def __init__(
        self,
        path: Path,
        *,
        taken_at: Optional[datetime] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        camera_model: Optional[str] = None,
        dwell_override_s: Optional[float] = None,
    ) -> None:
        self._path = path
        self._surface: Optional[Any] = None
        self._caption = ImageCaption.from_metadata(
            taken_at=taken_at,
            lat=lat,
            lon=lon,
            camera_model=camera_model,
        )
        self._dwell_override_s = dwell_override_s

    async def load(self, ctx: LoadContext) -> None:
        """Decode the image into a pygame Surface on a thread pool."""
        loop = asyncio.get_running_loop()
        self._surface = await loop.run_in_executor(None, self._decode)

    def _decode(self) -> Any:
        img = Image.open(self._path).convert("RGB")
        data = img.tobytes()
        return pygame.image.fromstring(data, img.size, img.mode)

    async def display(self, ctx: DisplayContext) -> None:
        """Blit the loaded surface, render overlays, and sleep for the dwell time."""
        if self._surface is None:
            await self.load(LoadContext())

        if ctx.screen is None:
            return

        w, h = ctx.width, ctx.height
        surf = pygame.transform.scale(self._surface, (w, h))

        if ctx.fade_duration_s > 0:
            await self._crossfade(ctx, surf)
        else:
            ctx.screen.blit(surf, (0, 0))

        # Render clock + caption on top of the scaled image.
        if ctx.overlay_renderer is not None:
            caption = self._caption if ctx.show_caption else None
            ctx.overlay_renderer.render(ctx.screen, w, h, caption)

        pygame.display.flip()

        dwell = (
            self._dwell_override_s
            if self._dwell_override_s is not None
            else ctx.dwell_s
        )
        await asyncio.sleep(dwell)

    async def _crossfade(self, ctx: DisplayContext, next_surf: Any) -> None:
        """Fade from the current screen content to *next_surf* over fade_duration_s."""
        import pygame  # noqa: PLC0415 -- pygame deferred to avoid transitive import

        w, h = ctx.width, ctx.height
        steps = max(1, int(ctx.fade_duration_s * 30))  # ~30 fps
        step_s = ctx.fade_duration_s / steps

        prev = pygame.Surface((w, h))
        prev.blit(ctx.screen, (0, 0))

        for i in range(1, steps + 1):
            alpha = int(255 * i / steps)
            ctx.screen.blit(prev, (0, 0))
            next_surf.set_alpha(alpha)
            ctx.screen.blit(next_surf, (0, 0))
            pygame.display.flip()
            await asyncio.sleep(step_s)

        next_surf.set_alpha(255)
        ctx.screen.blit(next_surf, (0, 0))
