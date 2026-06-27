"""pygame-based on-screen overlay: clock and per-image metadata caption.

The overlay renders two independent regions:

  Clock     -- current local time, top-right corner by default.
  Caption   -- date taken + location + camera model, bottom-left strip.

Both regions sit on a semi-transparent dark scrim so they remain legible
over any photo regardless of background brightness.

Design targets a "photo frame" aesthetic similar to Apple TV screensaver:
  - Clean system sans-serif at a comfortable reading size
  - Date in large weight, location and camera in a smaller secondary style
  - Smooth alpha scrim; no hard borders or outlines
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from malmberg_core.logging import get_logger

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Font priorities (pygame tries each until one is found)
# ---------------------------------------------------------------------------

_FONT_PRIORITIES = [
    "Ubuntu",
    "DejaVu Sans",
    "Liberation Sans",
    "FreeSans",
    "Arial",
    "Helvetica",
    None,  # pygame fallback (built-in bitmap font)
]

_FONT_CACHE: dict[tuple[Optional[str], int, bool], Any] = {}


def _get_font(size: int, bold: bool = False) -> Any:
    """Return a pygame.Font from the system, picking the best available."""
    import pygame.font  # type: ignore[import-not-found]

    key = (None, size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    for name in _FONT_PRIORITIES:
        try:
            font = pygame.font.SysFont(name, size, bold=bold)
            _FONT_CACHE[key] = font
            return font
        except Exception:  # noqa: BLE001
            continue

    font = pygame.font.Font(None, size)
    _FONT_CACHE[key] = font
    return font


# ---------------------------------------------------------------------------
# Scrim helper
# ---------------------------------------------------------------------------


def _draw_scrim(
    surface: Any,
    x: int,
    y: int,
    w: int,
    h: int,
    alpha: int = 140,
) -> None:
    """Draw a rounded semi-transparent dark rectangle onto *surface*."""
    import pygame  # type: ignore[import-not-found]

    scrim = pygame.Surface((w, h), pygame.SRCALPHA)
    scrim.fill((0, 0, 0, alpha))
    surface.blit(scrim, (x, y))


# ---------------------------------------------------------------------------
# Overlay config (kept lightweight -- no pydantic to avoid import cost)
# ---------------------------------------------------------------------------


class OverlayConfig:
    """Runtime settings for the overlay renderer."""

    __slots__ = (
        "show_clock",
        "show_caption",
        "clock_position",
        "font_size_primary",
        "font_size_secondary",
        "font_size_clock",
        "scrim_alpha",
        "margin",
        "line_spacing",
    )

    def __init__(
        self,
        *,
        show_clock: bool = True,
        show_caption: bool = True,
        clock_position: str = "top-right",
        font_size_primary: int = 36,
        font_size_secondary: int = 24,
        font_size_clock: int = 48,
        scrim_alpha: int = 140,
        margin: int = 28,
        line_spacing: int = 8,
    ) -> None:
        self.show_clock = show_clock
        self.show_caption = show_caption
        self.clock_position = clock_position
        self.font_size_primary = font_size_primary
        self.font_size_secondary = font_size_secondary
        self.font_size_clock = font_size_clock
        self.scrim_alpha = scrim_alpha
        self.margin = margin
        self.line_spacing = line_spacing


# ---------------------------------------------------------------------------
# Caption metadata (what we know about a particular image)
# ---------------------------------------------------------------------------


class ImageCaption:
    """Metadata to render below an image."""

    __slots__ = ("date_label", "location_label", "camera_label")

    def __init__(
        self,
        *,
        date_label: Optional[str] = None,
        location_label: Optional[str] = None,
        camera_label: Optional[str] = None,
    ) -> None:
        self.date_label = date_label
        self.location_label = location_label
        self.camera_label = camera_label

    @classmethod
    def from_metadata(
        cls,
        taken_at: Optional[datetime],
        lat: Optional[float],
        lon: Optional[float],
        camera_model: Optional[str],
        *,
        geocoder: Optional[Any] = None,
    ) -> "ImageCaption":
        """Build a caption from raw EXIF fields.

        *geocoder* is an optional callable `(lat, lon) -> str | None`; if
        supplied it is called synchronously (wrap in run_in_executor at the
        call site if needed).
        """
        date_label: Optional[str] = None
        if taken_at is not None:
            # Normalise to local wall time for display.
            local_dt = taken_at.astimezone()
            date_label = local_dt.strftime("%-d %B %Y")

        location_label: Optional[str] = None
        if lat is not None and lon is not None:
            if geocoder is not None:
                try:
                    location_label = geocoder(lat, lon)
                except Exception:  # noqa: BLE001
                    pass
            if location_label is None:
                # Graceful fallback: show decimal coords.
                ns = "N" if lat >= 0 else "S"
                ew = "E" if lon >= 0 else "W"
                location_label = f"{abs(lat):.2f} {ns}  {abs(lon):.2f} {ew}"

        cam = camera_model.strip() if camera_model else None

        return cls(
            date_label=date_label,
            location_label=location_label,
            camera_label=cam,
        )

    @property
    def is_empty(self) -> bool:
        return not any([self.date_label, self.location_label, self.camera_label])


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class OverlayRenderer:
    """Renders clock and caption overlays onto a pygame surface."""

    # Light off-white for primary text; a slightly warm grey for secondary.
    _COLOR_PRIMARY = (245, 245, 245)
    _COLOR_SECONDARY = (185, 185, 185)
    _COLOR_CLOCK = (255, 255, 255)

    def __init__(self, cfg: OverlayConfig) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def render_clock(self, surface: Any, width: int, height: int) -> None:
        """Draw the current local time onto *surface*."""

        cfg = self._cfg
        now = datetime.now()
        label = now.strftime("%-I:%M %p")

        font = _get_font(cfg.font_size_clock, bold=False)
        text_surf = font.render(label, True, self._COLOR_CLOCK)
        tw, th = text_surf.get_size()

        pad = 14
        m = cfg.margin

        if cfg.clock_position == "top-right":
            x = width - tw - m - pad
            y = m
        elif cfg.clock_position == "top-left":
            x = m
            y = m
        elif cfg.clock_position == "bottom-right":
            x = width - tw - m - pad
            y = height - th - m - pad
        else:
            x = m
            y = height - th - m - pad

        _draw_scrim(
            surface, x - pad, y - pad // 2, tw + pad * 2, th + pad, cfg.scrim_alpha
        )
        surface.blit(text_surf, (x, y))

    # ------------------------------------------------------------------
    # Caption
    # ------------------------------------------------------------------

    def render_caption(
        self,
        surface: Any,
        width: int,
        height: int,
        caption: ImageCaption,
    ) -> None:
        """Draw the image caption strip at the bottom of *surface*."""
        if caption.is_empty:
            return

        cfg = self._cfg
        m = cfg.margin
        ls = cfg.line_spacing

        font_primary = _get_font(cfg.font_size_primary, bold=False)
        font_secondary = _get_font(cfg.font_size_secondary, bold=False)

        lines: list[tuple[Any, Any]] = []  # (font, text)
        if caption.date_label:
            lines.append((font_primary, caption.date_label))
        if caption.location_label:
            lines.append((font_secondary, caption.location_label))
        if caption.camera_label:
            lines.append((font_secondary, caption.camera_label))

        if not lines:
            return

        rendered = [
            (
                f,
                f.render(
                    t,
                    True,
                    self._COLOR_PRIMARY if i == 0 else self._COLOR_SECONDARY,
                ),
            )
            for i, (f, t) in enumerate(lines)
        ]

        total_h = sum(s.get_height() for _, s in rendered) + ls * (len(rendered) - 1)
        max_w = max(s.get_width() for _, s in rendered)

        pad_x, pad_y = 18, 14
        block_x = m
        block_y = height - total_h - m - pad_y

        _draw_scrim(
            surface,
            block_x - pad_x,
            block_y - pad_y,
            max_w + pad_x * 2,
            total_h + pad_y * 2,
            cfg.scrim_alpha,
        )

        cy = block_y
        for _, surf in rendered:
            surface.blit(surf, (block_x, cy))
            cy += surf.get_height() + ls

    # ------------------------------------------------------------------
    # Convenience: render both regions in one call
    # ------------------------------------------------------------------

    def render(
        self,
        surface: Any,
        width: int,
        height: int,
        caption: Optional[ImageCaption] = None,
    ) -> None:
        cfg = self._cfg
        if cfg.show_clock:
            self.render_clock(surface, width, height)
        if cfg.show_caption and caption is not None:
            self.render_caption(surface, width, height, caption)


# ---------------------------------------------------------------------------
# Geocoding helper (optional; graceful fallback)
# ---------------------------------------------------------------------------


def make_geocoder(cache_dir: Optional[str] = None) -> Optional[Any]:
    """Return a (lat, lon) -> str geocoder backed by Nominatim if geopy is installed.

    Returns None if geopy is not installed; callers fall back to decimal coords.
    """
    try:
        from geopy.extra.rate_limiter import (
            RateLimiter,  # type: ignore[import-not-found]
        )
        from geopy.geocoders import Nominatim  # type: ignore[import-not-found]
    except ImportError:
        _log.debug("geopy not installed; location will display as decimal coordinates.")
        return None

    geolocator = Nominatim(user_agent="malmberg-display")
    reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1.0)

    def _geocode(lat: float, lon: float) -> Optional[str]:
        location = reverse(f"{lat}, {lon}", language="en", exactly_one=True)
        if location is None:
            return None
        addr = location.raw.get("address", {})
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("county")
        )
        state = addr.get("state")
        country_code = addr.get("country_code", "").upper()
        parts = [p for p in [city, state] if p]
        if not parts:
            return addr.get("country")
        if country_code != "US":
            parts.append(country_code)
        return ", ".join(parts)

    return _geocode


# ---------------------------------------------------------------------------
# Async clock ticker (used by DisplayApp to keep clock refreshed)
# ---------------------------------------------------------------------------


async def clock_tick_loop(
    surface: Any,
    renderer: OverlayRenderer,
    width: int,
    height: int,
    interval_s: float = 30.0,
) -> None:
    """Coroutine: re-render the clock region every *interval_s* seconds.

    Intended to run as a background task alongside the slideshow loop so that
    the clock stays fresh even during long-dwell images.  The caller is
    responsible for calling pygame.display.flip() after blit operations.
    """
    while True:
        renderer.render_clock(surface, width, height)
        await asyncio.sleep(interval_s)
