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

META_SCHEMA_VERSION = 1
"""Current MediaMetadata schema version stamped by extract_exif.

Bump this whenever a field is added to MediaMetadata that requires
re-reading the source file to populate. Items with a stale
meta.schema_version are transparently re-extracted on next read (see
MediaStore) so no manual re-ingest is ever required.
"""

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

    return Ok(
        MediaMetadata(
            taken_at=taken_at,
            camera_model=camera_model,
            lat=lat,
            lon=lon,
            width=width,
            height=height,
            sha256=digest,
            schema_version=META_SCHEMA_VERSION,
        )
    )


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
