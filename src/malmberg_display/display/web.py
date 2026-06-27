"""WebDisplay: render a URL via headless Chromium (playwright) as an overlay.

This module is only imported when `HardwareProfile.playwright_supported` is
True and `display.web_overlays` is enabled in config. On hardware that cannot
run Chromium (e.g. Pi Zero 2W), use a pygame-rendered clock widget instead.
"""

from __future__ import annotations

import asyncio
import io
from typing import Optional

import pygame  # type: ignore[import-not-found]
from playwright.async_api import async_playwright  # type: ignore[import-not-found]

from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext


class WebDisplay(Displayable):
    """Renders a URL to a pygame surface via playwright headless Chromium.

    Requires the `[web-overlays]` extra: `pip install malmberg[web-overlays]`.
    """

    def __init__(self, url: str, *, width: int = 1920, height: int = 1080) -> None:
        self._url = url
        self._width = width
        self._height = height
        self._screenshot: Optional[bytes] = None

    async def load(self, ctx: LoadContext) -> None:
        """Capture a screenshot of the URL into an in-memory PNG."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": self._width, "height": self._height}
            )
            await page.goto(self._url, wait_until="networkidle")
            self._screenshot = await page.screenshot(type="png")
            await browser.close()

    async def display(self, ctx: DisplayContext) -> None:
        """Composite the screenshot on top of the current pygame screen."""
        if self._screenshot is None:
            await self.load(ctx)

        if ctx.screen is None:
            return

        surf = pygame.image.load(io.BytesIO(self._screenshot))
        ctx.screen.blit(surf, (0, 0))
        pygame.display.flip()
        await asyncio.sleep(ctx.dwell_s)
