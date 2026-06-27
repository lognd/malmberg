"""t05_picture_display -- render a real image file via PictureDisplay + pygame."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from harness import TestContext, TestSkip

TITLE = "PictureDisplay render via pygame"
DEPENDS: list[str] = ["t04_pygame_display"]
INTERACTIVE = True

# Smallest valid 1x1 red JPEG in base64
_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAA"
    "AAAAAAAAAAAAAAAAAAAA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAA"
    "AAD/2gAMAwEAAhEDEQA/AJIAP//Z"
)


def _make_test_image(tmp: Path) -> Path:
    """Write a minimal valid JPEG to tmp and return its path."""
    import base64
    img_path = tmp / "test_image.jpg"
    img_path.write_bytes(base64.b64decode(_JPEG_B64))
    return img_path


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t05_picture_display")

    try:
        import pygame
    except ImportError:
        raise TestSkip("pygame not installed")

    from malmberg_core.hal import get_hardware_profile

    # Display availability is detected at pygame init time, not a profile flag.

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        img_path = _make_test_image(tmp)
        log.info("Test image: %s (%d bytes)", img_path, img_path.stat().st_size)

        from malmberg_display.display.picture import PictureDisplay
        from malmberg_display.display.proto import DisplayContext, LoadContext

        load_ctx = LoadContext(cache_dir=tmp)
        display_ctx = DisplayContext(width=800, height=480, fade_duration_s=0.0, dwell_s=1.5)

        async def _inner() -> None:
            pygame.init()
            try:
                d = PictureDisplay(img_path)
                log.info("Loading image...")
                await d.load(load_ctx)
                log.info("Displaying for ~1.5s...")
                await d.display(display_ctx)
            finally:
                pygame.quit()

        asyncio.run(_inner())
        log.info("PictureDisplay render completed without error.")

    if not ctx.no_interactive:
        ans = ctx.prompt("Did a red 1x1 image (solid red fill) appear on screen?")
        assert ans == "y", "User did not confirm image appeared"

    log.info("PictureDisplay test OK.")
