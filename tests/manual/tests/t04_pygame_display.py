"""t04_pygame_display -- open a pygame window and render a solid colour for 2 seconds."""

from __future__ import annotations

import importlib

from harness import TestContext, TestSkip

TITLE = "pygame window open + colour fill"
DEPENDS: list[str] = ["t03_hal_detection"]
INTERACTIVE = True


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t04_pygame_display")

    try:
        import pygame
    except ImportError:
        raise TestSkip("pygame not installed")

    from malmberg_core.hal import get_hardware_profile

    profile = get_hardware_profile()
    # has_display is not a profile field; we just try pygame.display.Info()
    # and let pygame tell us if no screen is available.

    log.info("Initialising pygame...")
    pygame.init()
    try:
        screen = pygame.display.set_mode((800, 480))
        pygame.display.set_caption("malmberg manual test - t04")
        screen.fill((30, 120, 60))
        pygame.display.flip()
        log.info("Green window should be visible on screen for ~2 seconds.")

        import time
        time.sleep(2)

        # Check for quit events so the window is responsive
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                break

    finally:
        pygame.quit()
        log.info("pygame closed.")

    if not ctx.no_interactive:
        ans = ctx.prompt("Did you see a green window appear for ~2 seconds?")
        assert ans == "y", "User did not confirm window appeared"

    log.info("pygame display test OK.")
