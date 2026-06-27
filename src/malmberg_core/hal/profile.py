"""HardwareProfile model -- the single source of truth for capability flags."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HardwareProfile(BaseModel):
    """Capability flags for the hardware this process is running on.

    Written by the provisioning script to hardware.toml; loaded at startup via
    `get_hardware_profile`. Application code branches on these fields; it never
    inspects `sys.platform` or `/proc/cpuinfo` directly.
    """

    name: str
    hw_video_decode: bool
    """mpv can use hardware-accelerated decode on this board."""
    gpio_available: bool
    """RPi GPIO pins are accessible (physical buttons, status LEDs)."""
    status_panel_bus: Literal["i2c", "spi", "none"]
    """Which bus drives the optional e-ink/OLED status panel."""
    max_preload_queue: int
    """Depth of the slideshow preload queue, scaled for available RAM."""
    playwright_supported: bool
    """Enough RAM to run a headless Chromium instance for web overlays."""

    @classmethod
    def fallback(cls) -> "HardwareProfile":
        """Minimal safe profile for unknown/generic x86 hardware."""
        return cls(
            name="generic-x86",
            hw_video_decode=False,
            gpio_available=False,
            status_panel_bus="none",
            max_preload_queue=4,
            playwright_supported=True,
        )
