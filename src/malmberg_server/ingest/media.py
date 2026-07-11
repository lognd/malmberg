"""EXIF extraction and file classification for ingested media."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from PIL import ExifTags, Image, ImageDraw, ImageFile, ImageOps, UnidentifiedImageError
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_core.models import MediaMetadata
from malmberg_server.ingest.errors import IngestError

_log = get_logger(__name__)

# Some phones/cameras upload partially-written or slightly-truncated files
# (interrupted sync, flaky wifi). Without this, Pillow raises on the final
# chunk instead of returning the image data it *did* manage to decode.
ImageFile.LOAD_TRUNCATED_IMAGES = True

# HEIC/HEIF/AVIF (the default iPhone photo format) are not decodable by
# stock Pillow -- it needs a libheif binding registered as a plugin. This is
# the single shared home for that registration; malmberg_display.display.picture
# does the same for the display-side render path since the two packages must
# not depend on each other. Best-effort: if pillow-heif is missing or fails to
# load (e.g. no libheif on this platform), image ingest must not crash --
# HEIC files will simply fail to decode downstream and be logged as such.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    _log.warning(
        "pillow-heif unavailable; HEIC/HEIF/AVIF files will fail to decode",
        exc_info=True,
    )

_VIDEO_EXTS = frozenset(
    {".mp4", ".mkv", ".mov", ".m4v", ".qt", ".avi", ".wmv", ".webm"}
)

# Thumbnail size for extracted video poster frames, in seconds into the clip.
# A couple seconds in tends to skip black opening frames / fade-ins; clips
# shorter than this just get their first decodable frame instead.
_POSTER_FRAME_OFFSET_S = 2.0

META_SCHEMA_VERSION = 2
"""Current MediaMetadata schema version stamped by extract_exif.

Bump this whenever a field is added to MediaMetadata that requires
re-reading the source file to populate. Items with a stale
meta.schema_version are transparently re-extracted on next read (see
MediaStore) so no manual re-ingest is ever required.

Version history:
  1 -> 2: added meta.place (offline reverse geocode of lat/lon).
"""

_geocoder = None
"""Lazily-imported reverse_geocoder module handle, or False once import has
been tried and failed. None means "not yet attempted"."""


def reverse_geocode(lat: float | None, lon: float | None) -> str | None:
    """Best-effort offline reverse geocode of (*lat*, *lon*) to a place label.

    Uses the optional `reverse_geocoder` package (offline, bundled cities
    dataset; part of the `geocode` extra -- NOT a base dependency, and never
    installed on the display/Pi). Returns None if coordinates are missing,
    the package is not installed, or lookup fails for any reason -- this
    must never raise or block ingestion. Runs a single lookup at a time
    (mode=1) to avoid reverse_geocoder's default multiprocessing pool, which
    is unnecessary overhead for one-off single-photo lookups.
    """
    global _geocoder
    if lat is None or lon is None:
        return None
    if _geocoder is False:
        return None
    if _geocoder is None:
        try:
            import reverse_geocoder as rg

            _geocoder = rg
        except ImportError:
            _log.warning(
                "reverse_geocoder unavailable; photo places will not be "
                "populated (install the 'geocode' extra on the server)"
            )
            _geocoder = False
            return None
    try:
        result = _geocoder.get((lat, lon), mode=1)
        city = (result.get("name") or "").strip()
        region = (result.get("admin1") or "").strip()
        country = (result.get("cc") or "").strip()
        parts = [p for p in (city, region, country) if p]
        return ", ".join(parts) if parts else None
    except Exception:
        _log.warning("reverse_geocode failed for (%s, %s)", lat, lon, exc_info=True)
        return None


# EXIF tag IDs we care about, resolved by name for readability.
_TAG_BY_NAME = {v: k for k, v in ExifTags.TAGS.items()}
_TAG_DATETIME_ORIGINAL = _TAG_BY_NAME.get("DateTimeOriginal")  # 36867 (Exif sub-IFD)
_TAG_DATETIME = _TAG_BY_NAME.get("DateTime")  # 306 (IFD0 fallback)
_TAG_MAKE = _TAG_BY_NAME.get("Make")
_TAG_MODEL = _TAG_BY_NAME.get("Model")
_GPS_TAGS = {v: k for k, v in ExifTags.GPSTAGS.items()}


def sha256_of_file(path: Path) -> str:
    """Return the SHA-256 hex digest of *path* without loading it fully into RAM."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_exif(path: Path) -> Result[MediaMetadata, IngestError]:
    """Extract EXIF metadata from *path* and return a populated MediaMetadata.

    Video files receive only sha256 and ingest_at (no EXIF parsing attempt).
    On any Pillow error the function returns Err(IngestError.ExifError) rather
    than raising; callers should continue with a minimal MediaMetadata if EXIF
    is not critical for their use case.
    """
    try:
        digest = sha256_of_file(path)
    except OSError:
        return Err(IngestError.IOError)

    if path.suffix.lower() in _VIDEO_EXTS:
        return Ok(MediaMetadata(sha256=digest, schema_version=META_SCHEMA_VERSION))

    try:
        img = Image.open(path)
        width, height = img.size
        # getexif() returns the top-level IFD0 (Make/Model/DateTime/Orientation).
        # DateTimeOriginal and GPS live in dedicated sub-IFDs, fetched separately.
        exif_obj = img.getexif()
        raw_exif = dict(exif_obj) if exif_obj else {}
        exif_ifd = _safe_ifd(exif_obj, ExifTags.IFD.Exif)
        gps_ifd = _safe_ifd(exif_obj, ExifTags.IFD.GPSInfo)
    except UnidentifiedImageError:
        return Err(IngestError.ExifError)
    except OSError:
        return Err(IngestError.IOError)
    except Exception:
        return Err(IngestError.ExifError)

    taken_at: datetime | None = None
    camera_model: str | None = None
    lat: float | None = None
    lon: float | None = None

    if raw_exif or exif_ifd:
        # Prefer DateTimeOriginal (Exif sub-IFD); fall back to IFD0 DateTime.
        raw_dt = None
        if _TAG_DATETIME_ORIGINAL:
            raw_dt = exif_ifd.get(_TAG_DATETIME_ORIGINAL)
        if raw_dt is None and _TAG_DATETIME:
            raw_dt = raw_exif.get(_TAG_DATETIME)
        if isinstance(raw_dt, str):
            try:
                taken_at = datetime.strptime(
                    raw_dt.strip(), "%Y:%m:%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        make = raw_exif.get(_TAG_MAKE, "").strip() if _TAG_MAKE else ""
        model_str = raw_exif.get(_TAG_MODEL, "").strip() if _TAG_MODEL else ""
        if make or model_str:
            camera_model = f"{make} {model_str}".strip() if make else model_str

        if gps_ifd:
            lat, lon = _parse_gps(gps_ifd)

    place = reverse_geocode(lat, lon)

    return Ok(
        MediaMetadata(
            taken_at=taken_at,
            camera_model=camera_model,
            lat=lat,
            lon=lon,
            place=place,
            width=width,
            height=height,
            sha256=digest,
            schema_version=META_SCHEMA_VERSION,
        )
    )


def make_thumbnail(
    src: Path, dest: Path, size: int, *, is_video: bool = False
) -> Result[Path, IngestError]:
    """Write a square-bounded JPEG thumbnail of *src* to *dest*.

    Images are EXIF-oriented and scaled to fit within *size* x *size*, with
    any non-RGB mode (CMYK/P/LA/RGBA/...) flattened to RGB before save so the
    JPEG encoder never chokes. Videos get a real poster frame extracted a
    couple seconds into the clip (see `_extract_video_frame`); if extraction
    fails for any reason the previous drawn play-glyph placeholder is used
    instead, so a thumbnail is always produced. Returns Ok(dest) or an
    IngestError if nothing could be written at all.
    """
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if is_video:
            img = _extract_video_frame(src, size)
            if img is None:
                img = _placeholder_video_tile(size)
        else:
            decoded = Image.open(src)
            img = ImageOps.exif_transpose(decoded)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((size, size))
        img.save(dest, "JPEG", quality=82)
        return Ok(dest)
    except UnidentifiedImageError:
        _log.warning("thumbnail: undecodable image, skipping: %s", src)
        return Err(IngestError.ExifError)
    except OSError:
        _log.warning("thumbnail: I/O error reading %s", src, exc_info=True)
        return Err(IngestError.IOError)
    except Exception:
        _log.warning("thumbnail: failed to render %s", src, exc_info=True)
        return Err(IngestError.ExifError)


def _placeholder_video_tile(size: int) -> Image.Image:
    """Return the drawn grey play-glyph tile, used when frame extraction fails."""
    img = Image.new("RGB", (size, size), (32, 34, 40))
    draw = ImageDraw.Draw(img)
    c = size / 2
    r = size / 6
    draw.polygon(
        [(c - r, c - r * 1.25), (c - r, c + r * 1.25), (c + r * 1.4, c)],
        fill=(210, 210, 216),
    )
    return img


def _extract_video_frame(src: Path, size: int) -> Image.Image | None:
    """Grab a representative frame from *src* as a scaled RGB poster image.

    Uses imageio-ffmpeg's bundled ffmpeg binary (no system ffmpeg install
    required) to pull one frame a couple seconds into the clip, falling back
    to the first decodable frame for short clips, then overlays a small play
    glyph so it still reads as a video in the grid. Returns None -- never
    raises -- on any failure so the caller can fall back to the placeholder.
    """
    try:
        import imageio_ffmpeg
    except Exception:
        _log.warning("imageio-ffmpeg unavailable; using placeholder video tile")
        return None

    try:
        frame_bytes: bytes | None = None
        width = height = 0
        for offset in (_POSTER_FRAME_OFFSET_S, 0.0):
            reader = imageio_ffmpeg.read_frames(str(src), pix_fmt="rgb24")
            meta = next(reader)
            width, height = meta["size"]
            if offset:
                # Skip ahead by dropping decoded frames until roughly `offset`
                # seconds in, based on the reported fps; short clips exhaust
                # the reader before reaching it and fall through to offset=0.
                fps = meta.get("fps") or 30.0
                skip_frames = int(offset * fps)
                frame = None
                for i, frame in enumerate(reader):
                    if i >= skip_frames:
                        break
                if frame is not None:
                    frame_bytes = frame
                    break
            else:
                frame_bytes = next(reader, None)
                break
        if frame_bytes is None or not width or not height:
            _log.warning("video frame extraction produced no frame: %s", src)
            return None

        img = Image.frombytes("RGB", (width, height), frame_bytes)
        img.thumbnail((size, size))
        _overlay_play_glyph(img)
        return img
    except Exception:
        _log.warning("video frame extraction failed for %s", src, exc_info=True)
        return None


def _overlay_play_glyph(img: Image.Image) -> None:
    """Draw a small translucent play triangle over *img* in place."""
    w, h = img.size
    glyph_r = min(w, h) / 8
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    circle_r = glyph_r * 1.4
    cx, cy = w / 2, h / 2
    draw.ellipse(
        [cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
        fill=(20, 20, 24, 140),
    )
    draw.polygon(
        [
            (cx - glyph_r * 0.6, cy - glyph_r),
            (cx - glyph_r * 0.6, cy + glyph_r),
            (cx + glyph_r * 0.9, cy),
        ],
        fill=(240, 240, 244, 230),
    )
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def _safe_ifd(exif_obj: object, ifd_id: object) -> dict:
    """Return the requested EXIF sub-IFD as a dict, or {} if unavailable."""
    try:
        return dict(exif_obj.get_ifd(ifd_id))  # type: ignore[attr-defined]
    except Exception:
        return {}


def _parse_gps(gps_data: dict) -> tuple[float | None, float | None]:
    """Convert raw EXIF GPS dict to decimal (lat, lon), or (None, None) on error."""
    try:
        lat_dms = gps_data.get(2)
        lat_ref = gps_data.get(1, "N")
        lon_dms = gps_data.get(4)
        lon_ref = gps_data.get(3, "E")
        if lat_dms is None or lon_dms is None:
            return None, None
        lat = _dms_to_decimal(lat_dms, lat_ref)
        lon = _dms_to_decimal(lon_dms, lon_ref)
        return lat, lon
    except Exception:
        return None, None


def _dms_to_decimal(dms: tuple, ref: str) -> float:
    """Convert degrees/minutes/seconds tuple to signed decimal degrees."""
    d, m, s = (float(x) for x in dms)
    value = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        value = -value
    return value
