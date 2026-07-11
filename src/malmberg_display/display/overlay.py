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


_GRADIENT_CACHE: dict[tuple[int, int, int], Any] = {}


def _bottom_gradient(width: int, height: int, max_alpha: int) -> Any:
    """Return a cached full-width surface that fades transparent->dark downward.

    Used as a soft scrim behind bottom captions so text stays legible over any
    photo without a hard-edged box.
    """
    import pygame  # type: ignore[import-not-found]

    key = (width, height, max_alpha)
    cached = _GRADIENT_CACHE.get(key)
    if cached is not None:
        return cached

    grad = pygame.Surface((width, height), pygame.SRCALPHA)
    for row in range(height):
        # Ease-in so the darkening is gentle at the top, stronger at the bottom.
        frac = (row / max(1, height - 1)) ** 1.6
        alpha = int(max_alpha * frac)
        pygame.draw.line(grad, (0, 0, 0, alpha), (0, row), (width, row))
    _GRADIENT_CACHE[key] = grad
    return grad


def _blit_text_shadow(
    surface: Any,
    font: Any,
    text: str,
    pos: tuple[int, int],
    color: tuple[int, int, int],
    *,
    right_align: bool = False,
) -> tuple[int, int]:
    """Blit *text* with a soft drop shadow; return the rendered (w, h)."""
    fg = font.render(text, True, color)
    shadow = font.render(text, True, (0, 0, 0))
    x, y = pos
    if right_align:
        x -= fg.get_width()
    surface.blit(shadow, (x + 2, y + 2))
    surface.blit(fg, (x, y))
    return fg.get_size()


# ---------------------------------------------------------------------------
# Overlay config (kept lightweight -- no pydantic to avoid import cost)
# ---------------------------------------------------------------------------


class OverlayConfig:
    """Runtime settings for the overlay renderer."""

    __slots__ = (
        "show_clock",
        "show_caption",
        "show_camera",
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
        show_camera: bool = False,
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
        self.show_camera = show_camera
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
            # Normalise to local wall time; friendly "April 26, 2006" form.
            local_dt = taken_at.astimezone()
            date_label = local_dt.strftime("%B %-d, %Y")

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
        """Draw the current time (large) and date (below) in the top-right."""
        cfg = self._cfg
        now = datetime.now()
        time_label = now.strftime("%-I:%M %p")
        date_label = now.strftime("%A, %B %-d")

        time_font = _get_font(cfg.font_size_clock, bold=False)
        date_font = _get_font(cfg.font_size_secondary, bold=False)
        m = cfg.margin
        right = width - m

        tw, th = _blit_text_shadow(
            surface, time_font, time_label, (right, m), self._COLOR_CLOCK,
            right_align=True,
        )
        _blit_text_shadow(
            surface, date_font, date_label, (right, m + th + 2),
            self._COLOR_SECONDARY, right_align=True,
        )

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
        """Draw labeled photo metadata (Date / Location / Camera) bottom-left."""
        if caption.is_empty:
            return

        cfg = self._cfg
        m = cfg.margin
        ls = cfg.line_spacing + 4

        label_font = _get_font(cfg.font_size_secondary, bold=True)
        value_font = _get_font(cfg.font_size_secondary, bold=False)

        rows: list[tuple[str, str]] = []
        if caption.date_label:
            rows.append(("Date", caption.date_label))
        if caption.location_label:
            rows.append(("Location", caption.location_label))
        if caption.camera_label and cfg.show_camera:
            rows.append(("Camera", caption.camera_label))
        if not rows:
            return

        # Column: align all values past the widest label.
        col_x = m + max(label_font.size(lbl)[0] for lbl, _ in rows) + 24
        line_h = value_font.get_height()
        total_h = line_h * len(rows) + ls * (len(rows) - 1)

        grad_h = min(height, total_h + m * 2 + int(height * 0.10))
        surface.blit(
            _bottom_gradient(width, grad_h, min(220, cfg.scrim_alpha + 60)),
            (0, height - grad_h),
        )

        y = height - m - total_h
        for lbl, val in rows:
            _blit_text_shadow(surface, label_font, lbl, (m, y), self._COLOR_SECONDARY)
            _blit_text_shadow(surface, value_font, val, (col_x, y), self._COLOR_PRIMARY)
            y += line_h + ls

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
