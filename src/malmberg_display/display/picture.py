"""PictureDisplay: render a still image via pygame with optional cross-fade."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import pygame  # type: ignore[import-not-found]
from PIL import Image  # type: ignore[import-not-found]

from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext


class PictureDisplay(Displayable):
    """Displays a single image file.

    load() decodes the file with Pillow and converts it to a pygame Surface.
    display() blits the surface and sleeps for the configured dwell time.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._surface: Optional[Any] = None

    async def load(self, ctx: LoadContext) -> None:
        """Decode the image into a pygame Surface on a thread pool."""
        loop = asyncio.get_running_loop()
        self._surface = await loop.run_in_executor(None, self._decode)

    def _decode(self) -> Any:
        img = Image.open(self._path).convert("RGB")
        data = img.tobytes()
        return pygame.image.fromstring(data, img.size, img.mode)

    async def display(self, ctx: DisplayContext) -> None:
        """Blit the loaded surface and sleep for the dwell time."""
        if self._surface is None:
            await self.load(LoadContext())

        if ctx.screen is None:
            return

        surf = pygame.transform.scale(self._surface, (ctx.width, ctx.height))
        ctx.screen.blit(surf, (0, 0))
        pygame.display.flip()
        await asyncio.sleep(ctx.dwell_s)
