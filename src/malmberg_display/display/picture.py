"""PictureDisplay: image renderer with aspect-fit, blurred backdrop, and cross-fade."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import pygame  # type: ignore[import-not-found]
from PIL import Image, ImageFilter, ImageOps  # type: ignore[import-not-found]

from malmberg_display.display.overlay import ImageCaption
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext

# Gaussian blur radius for the backdrop, as a fraction of the image's long edge.
_BG_BLUR_FRACTION = 0.02
# Alpha of the black wash over the blurred background so the photo stands out.
_BG_DARKEN_ALPHA = 150


def _scaled_size(
    iw: int, ih: int, tw: int, th: int, *, cover: bool
) -> tuple[int, int]:
    """Return (w, h) that fits *iw x ih* into *tw x th* preserving aspect ratio.

    cover=False -> "contain" (whole image visible, letterboxed).
    cover=True  -> "cover"   (fills the target, cropping the overflow).
    """
    scale_w, scale_h = tw / iw, th / ih
    scale = max(scale_w, scale_h) if cover else min(scale_w, scale_h)
    return max(1, round(iw * scale)), max(1, round(ih * scale))


def _compose_frame(fg_src: Any, bg_src: Any, tw: int, th: int) -> Any:
    """Compose a full-screen frame: Gaussian-blurred cover fill behind the fitted photo.

    This is the "professional photo-frame" look -- the image is never stretched;
    portrait/odd-ratio photos get a soft blurred version of themselves as the
    backdrop instead of hard black bars.  *bg_src* is a pre-blurred copy so
    scaling it stays smooth (no blocky pixelation at the edges).
    """
    iw, ih = fg_src.get_size()
    frame = pygame.Surface((tw, th)).convert()

    # Background: cover-scale the already-blurred image, then darken.
    cw, ch = _scaled_size(iw, ih, tw, th, cover=True)
    bg = pygame.transform.smoothscale(bg_src, (cw, ch))
    frame.blit(bg, ((tw - cw) // 2, (th - ch) // 2))
    dark = pygame.Surface((tw, th), pygame.SRCALPHA)
    dark.fill((0, 0, 0, _BG_DARKEN_ALPHA))
    frame.blit(dark, (0, 0))

    # Foreground: contain-scale, centered, unstretched.
    fw, fh = _scaled_size(iw, ih, tw, th, cover=False)
    fg = pygame.transform.smoothscale(fg_src, (fw, fh))
    frame.blit(fg, ((tw - fw) // 2, (th - fh) // 2))
    return frame


class PictureDisplay(Displayable):
    """Displays a single image file with a blurred backdrop and metadata overlay.

    load() decodes the file with Pillow (applying EXIF orientation) into a pygame
    Surface and builds the caption. display() composes an aspect-correct frame,
    cross-fades from the current screen content, then draws the overlay.

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
        taken_at: Optional[Any] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        camera_model: Optional[str] = None,
        dwell_override_s: Optional[float] = None,
    ) -> None:
        self._path = path
        self._surface: Optional[Any] = None
        self._bg: Optional[Any] = None
        self._taken_at = taken_at
        self._lat = lat
        self._lon = lon
        self._camera_model = camera_model
        self._caption: Optional[ImageCaption] = None
        self._dwell_override_s = dwell_override_s

    def __repr__(self) -> str:
        """Friendly name (the filename) for status/history readouts."""
        return self._path.name

    async def load(self, ctx: LoadContext) -> None:
        """Decode the image and build the caption off the event loop."""
        loop = asyncio.get_running_loop()
        self._surface, self._bg = await loop.run_in_executor(None, self._decode)
        # Caption building may call a (possibly network-bound) geocoder.
        self._caption = await loop.run_in_executor(
            None,
            lambda: ImageCaption.from_metadata(
                taken_at=self._taken_at,
                lat=self._lat,
                lon=self._lon,
                camera_model=self._camera_model,
                geocoder=ctx.geocoder,
            ),
        )

    def _decode(self) -> tuple[Any, Any]:
        """Decode with Pillow (EXIF-oriented); return (photo, pre-blurred backdrop)."""
        img = ImageOps.exif_transpose(Image.open(self._path)).convert("RGB")
        fg = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
        radius = max(2, round(max(img.size) * _BG_BLUR_FRACTION))
        blurred = img.filter(ImageFilter.GaussianBlur(radius))
        bg = pygame.image.fromstring(blurred.tobytes(), blurred.size, blurred.mode)
        return fg, bg

    async def display(self, ctx: DisplayContext) -> None:
        """Compose an aspect-correct frame, cross-fade in, draw overlay, then dwell."""
        if self._surface is None:
            await self.load(LoadContext())

        if ctx.screen is None:
            return

        w, h = ctx.width, ctx.height
        frame = _compose_frame(self._surface, self._bg, w, h)

        if ctx.fade_duration_s > 0:
            await self._crossfade(ctx, frame)
        else:
            ctx.screen.blit(frame, (0, 0))

        if ctx.overlay_renderer is not None:
            caption = self._caption if ctx.show_caption else None
            ctx.overlay_renderer.render(ctx.screen, w, h, caption)

        pygame.display.flip()
        # Snapshot the finished frame so the toast task can repaint over it and
        # cleanly restore it when the toast expires.
        ctx.base_frame = ctx.screen.copy()

        dwell = (
            self._dwell_override_s
            if self._dwell_override_s is not None
            else ctx.dwell_s
        )
        await asyncio.sleep(dwell)

    async def _crossfade(self, ctx: DisplayContext, next_frame: Any) -> None:
        """Time-based fade to *next_frame* -- smooth even if some frames are slow."""
        loop = asyncio.get_running_loop()
        prev = ctx.screen.copy()
        next_frame = next_frame.convert()  # display format => fast alpha blits
        start = loop.time()
        dur = ctx.fade_duration_s

        while True:
            t = (loop.time() - start) / dur
            if t >= 1.0:
                break
            next_frame.set_alpha(int(255 * t))
            ctx.screen.blit(prev, (0, 0))
            ctx.screen.blit(next_frame, (0, 0))
            # Keep the clock painted every frame so it stays glued (no flash).
            if ctx.overlay_renderer is not None and ctx.show_clock:
                ctx.overlay_renderer.render_clock(ctx.screen, ctx.width, ctx.height)
            pygame.display.flip()
            await asyncio.sleep(1 / 60)

        next_frame.set_alpha(255)
        ctx.screen.blit(next_frame, (0, 0))
