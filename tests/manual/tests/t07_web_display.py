"""t07_web_display -- take a Playwright screenshot and render it via pygame."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from harness import TestContext, TestSkip

TITLE = "WebDisplay screenshot + render via pygame"
DEPENDS: list[str] = ["t04_pygame_display"]
INTERACTIVE = True


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t07_web_display")

    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        raise TestSkip("playwright not installed")

    try:
        import pygame  # noqa: F401
    except ImportError:
        raise TestSkip("pygame not installed")

    from malmberg_core.hal import get_hardware_profile

    if not get_hardware_profile().playwright_supported:
        raise TestSkip("Hardware profile reports playwright_supported=False")

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)

        from malmberg_display.display.proto import DisplayContext, LoadContext
        from malmberg_display.display.web import WebDisplay

        load_ctx = LoadContext(cache_dir=tmp)
        display_ctx = DisplayContext(
            width=800, height=480, fade_duration_s=0.0, dwell_s=2.0
        )

        # Use a simple data: URL so no network required
        url = "data:text/html,<body style='background:orange;margin:0'><h1>malmberg</h1></body>"

        async def _inner() -> None:
            import pygame

            pygame.init()
            try:
                d = WebDisplay(url)
                log.info("Loading web page (screenshot via Playwright)...")
                await d.load(load_ctx)
                log.info("Rendering screenshot via pygame for ~2s...")
                await d.display(display_ctx)
            finally:
                pygame.quit()

        asyncio.run(_inner())
        log.info("WebDisplay completed without error.")

    if not ctx.no_interactive:
        ans = ctx.prompt(
            "Did an orange web page with 'malmberg' heading appear for ~2s?"
        )
        assert ans == "y", "User did not confirm web page appeared"

    log.info("WebDisplay test OK.")
