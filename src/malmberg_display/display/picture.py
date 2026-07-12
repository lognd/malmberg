"""PictureDisplay: image renderer with aspect-fit, blurred backdrop, and cross-fade."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import pygame  # type: ignore[import-not-found]
from PIL import (  # type: ignore[import-not-found]
    Image,
    ImageFile,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)

from malmberg_core.logging import get_logger
from malmberg_display.display.overlay import ImageCaption
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext

_log = get_logger(__name__)

# Tolerate partially-downloaded/interrupted files rather than raising on the
# final chunk (mirrors malmberg_server.ingest.media, which cannot be imported
# from here without creating a server -> display layering violation).
ImageFile.LOAD_TRUNCATED_IMAGES = True

# HEIC/HEIF/AVIF (default iPhone photo format) need libheif registered as a
# Pillow plugin -- stock Pillow cannot decode them. This mirrors the same
# best-effort registration in malmberg_server.ingest.media; kept duplicated
# rather than shared because server and display are deliberately independent
# packages (no display -> server or server -> display import is allowed).
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    _log.warning(
        "pillow-heif unavailable; HEIC/HEIF/AVIF files will fail to decode",
        exc_info=True,
    )

# Gaussian blur radius for the backdrop, as a fraction of the image's long edge.
_BG_BLUR_FRACTION = 0.02
# Alpha of the black wash over the blurred background so the photo stands out.
_BG_DARKEN_ALPHA = 150


def _scaled_size(iw: int, ih: int, tw: int, th: int, *, cover: bool) -> tuple[int, int]:
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
    # No .convert() here: this runs on a worker thread during load(), and
    # convert() touches the display's pixel format.  display() converts the
    # finished frame on the main thread, which is a single cheap copy.
    frame = pygame.Surface((tw, th))

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
        # The screen-sized, ready-to-blit frame built by load(). The full-res
        # decode is deliberately NOT retained; see load()/release().
        self._frame: Optional[Any] = None
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
        """Decode and fully compose the frame off the event loop, ready to blit.

        Everything expensive happens here, on a worker thread, while the
        PREVIOUS photo is still on screen: decode, blur, both scales, compose.
        display() is then just a fade between two ready surfaces, so the swap
        never stalls the event loop.

        The full-resolution decode is dropped once composed -- only the
        screen-sized frame is kept.  Holding the originals meant every item in
        the 32-deep history and the preload queue pinned tens of MB of surfaces
        (a 12 MP photo is ~36 MB raw), which exhausted the Pi's memory.

        An undecodable file (corrupt, unsupported format, HEIC without a working
        decoder, etc.) is logged and leaves `_frame` as None rather than raising
        -- `display()` then skips the frame instead of crashing the producer.
        """
        loop = asyncio.get_running_loop()
        decoded = await loop.run_in_executor(None, self._decode)
        if decoded is None:
            self._frame = None
            return
        fg, bg = decoded
        w, h = ctx.screen_width, ctx.screen_height
        self._frame = await loop.run_in_executor(None, _compose_frame, fg, bg, w, h)
        _log.debug("picture: composed %dx%d frame for %s", w, h, self._path.name)

        if self._caption is not None:
            return  # already built on a previous load (history revisit)
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

    def release(self) -> None:
        """Drop the composed frame; it is re-made on demand if shown again.

        Called once an item leaves the screen so that history and the preload
        queue hold only paths and captions, not surfaces.
        """
        self._frame = None

    def _decode(self) -> Optional[tuple[Any, Any]]:
        """Decode with Pillow (EXIF-oriented); return (photo, pre-blurred backdrop).

        Returns None on any decode failure (undecodable format, I/O error)
        instead of raising, so the caller can degrade gracefully.
        """
        try:
            raw = ImageOps.exif_transpose(Image.open(self._path))
            if raw.mode != "RGB":
                raw = raw.convert("RGB")
            img = raw
            fg = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
            radius = max(2, round(max(img.size) * _BG_BLUR_FRACTION))
            blurred = img.filter(ImageFilter.GaussianBlur(radius))
            bg = pygame.image.fromstring(blurred.tobytes(), blurred.size, blurred.mode)
            return fg, bg
        except UnidentifiedImageError:
            _log.warning("picture: undecodable image, skipping: %s", self._path)
            return None
        except OSError:
            _log.warning("picture: I/O error decoding %s", self._path, exc_info=True)
            return None
        except Exception:
            _log.warning("picture: failed to decode %s", self._path, exc_info=True)
            return None

    async def display(self, ctx: DisplayContext) -> None:
        """Compose an aspect-correct frame, cross-fade in, draw overlay, then dwell."""
        if ctx.screen is None:
            return

        w, h = ctx.width, ctx.height
        if self._frame is None:
            # Not pre-composed: a history revisit whose frame was released, or a
            # load() that never ran. Re-make it (costs a decode) rather than
            # skip.
            # The caption survives release(), so no geocoder is needed here.
            await self.load(LoadContext(screen_width=w, screen_height=h))

        if self._frame is None:
            # Decode failed (see _decode); skip this frame entirely rather
            # than crash -- no blit, no dwell, the slideshow moves right on.
            _log.warning("picture: skipping undisplayable file: %s", self._path)
            return

        frame = self._frame.convert()  # display format => fast alpha blits

        ctx.rendering = True  # keep the toast task off the screen while drawing
        try:
            if ctx.fade_duration_s > 0:
                await self._crossfade(ctx, frame)
            else:
                ctx.screen.blit(frame, (0, 0))

            if ctx.overlay_renderer is not None:
                caption = self._caption if ctx.show_caption else None
                ctx.overlay_renderer.render(ctx.screen, w, h, caption)

            pygame.display.flip()
            # Snapshot the finished frame so the toast task can repaint over it
            # and cleanly restore it when the toast expires.
            ctx.base_frame = ctx.screen.copy()
        finally:
            ctx.rendering = False

        dwell = (
            self._dwell_override_s
            if self._dwell_override_s is not None
            else ctx.dwell_s
        )
        # Interruptible dwell: a Next tap or producer switch sets skip_event to
        # end the wait early, so manual controls override the queue instantly.
        try:
            if ctx.skip_event is not None:
                try:
                    await asyncio.wait_for(ctx.skip_event.wait(), timeout=dwell)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(dwell)
        finally:
            # The frame is on screen (and snapshotted in ctx.base_frame); it no
            # longer needs to be held here. Releasing keeps history from pinning
            # a surface per item.
            self.release()

    async def _crossfade(self, ctx: DisplayContext, next_frame: Any) -> None:
        """Time-based fade to *next_frame* -- smooth even if some frames are slow."""
        loop = asyncio.get_running_loop()
        prev = ctx.screen.copy()
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
