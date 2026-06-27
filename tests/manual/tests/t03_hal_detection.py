"""t03_hal_detection -- detect and report the hardware profile of this machine."""

from __future__ import annotations

from harness import TestContext

TITLE = "HAL hardware profile detection"
DEPENDS: list[str] = ["t01_prereqs"]
INTERACTIVE = False


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t03_hal_detection")

    from malmberg_core.hal import get_hardware_profile

    profile = get_hardware_profile()
    log.info("Hardware profile name:       %s", profile.name)
    log.info("  hw_video_decode      = %s", profile.hw_video_decode)
    log.info("  gpio_available       = %s", profile.gpio_available)
    log.info("  status_panel_bus     = %s", profile.status_panel_bus)
    log.info("  playwright_supported = %s", profile.playwright_supported)
    log.info("  max_preload_queue    = %d", profile.max_preload_queue)

    assert profile.name, "Profile must have a non-empty name"
    assert profile.max_preload_queue >= 1, "max_preload_queue must be >= 1"

    log.info("HAL detection OK.")
