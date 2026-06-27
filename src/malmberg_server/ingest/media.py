"""EXIF extraction and file classification for ingested media."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError
from typani.result import Err, Ok, Result

from malmberg_core.models import MediaMetadata
from malmberg_server.ingest.errors import IngestError

_VIDEO_EXTS = frozenset(
    {".mp4", ".mkv", ".mov", ".m4v", ".qt", ".avi", ".wmv", ".webm"}
)

# EXIF tag IDs we care about, resolved by name for readability.
_TAG_BY_NAME = {v: k for k, v in ExifTags.TAGS.items()}
_TAG_DATETIME_ORIGINAL = _TAG_BY_NAME.get("DateTimeOriginal")
_TAG_MAKE = _TAG_BY_NAME.get("Make")
_TAG_MODEL = _TAG_BY_NAME.get("Model")
_GPS_INFO = _TAG_BY_NAME.get("GPSInfo")
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
        return Ok(MediaMetadata(sha256=digest))

    try:
        img = Image.open(path)
        width, height = img.size
        # getexif() is the public Pillow 6+ API; returns an empty Exif object if absent.
        exif_obj = img.getexif()
        raw_exif = dict(exif_obj) if exif_obj else {}
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

    if raw_exif:
        if _TAG_DATETIME_ORIGINAL and (raw := raw_exif.get(_TAG_DATETIME_ORIGINAL)):
            try:
                taken_at = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass

        make = raw_exif.get(_TAG_MAKE, "").strip() if _TAG_MAKE else ""
        model_str = raw_exif.get(_TAG_MODEL, "").strip() if _TAG_MODEL else ""
        if make or model_str:
            camera_model = f"{make} {model_str}".strip() if make else model_str

        if _GPS_INFO and (gps_data := raw_exif.get(_GPS_INFO)):
            lat, lon = _parse_gps(gps_data)

    return Ok(
        MediaMetadata(
            taken_at=taken_at,
            camera_model=camera_model,
            lat=lat,
            lon=lon,
            width=width,
            height=height,
            sha256=digest,
        )
    )


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
