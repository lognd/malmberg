"""Handle streaming file uploads: hash, EXIF, move, index."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_core.models import MediaItem
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import extract_exif
from malmberg_server.ingest.store import MediaStore

_log = get_logger(__name__)

_VIDEO_EXTS = frozenset(
    {".mp4", ".mkv", ".mov", ".m4v", ".qt", ".avi", ".wmv", ".webm"}
)


async def handle_upload(
    file: UploadFile,
    store: MediaStore,
    media_root: Path,
    upload_root: Path,
    max_bytes: int,
) -> Result[MediaItem, IngestError]:
    """Stream *file* to disk, hash it, extract EXIF, and add it to *store*.

    Steps:
    1. Stream to ``upload_root/<filename>``; abort if size exceeds *max_bytes*.
    2. Compute SHA-256 and reject duplicates.
    3. Extract EXIF metadata (best-effort; failures produce a minimal record).
    4. Move to ``media_root/YYYY/MM/DD/<filename>``.
    5. Add to *store* and return the new MediaItem.
    """
    if file.filename is None:
        return Err(IngestError.IOError)

    staging = upload_root / file.filename
    sha = hashlib.sha256()
    total = 0

    try:
        staging.parent.mkdir(parents=True, exist_ok=True)
        with open(staging, "wb") as dest:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    dest.close()
                    staging.unlink(missing_ok=True)
                    return Err(IngestError.FileTooLarge)
                sha.update(chunk)
                dest.write(chunk)
    except OSError:
        return Err(IngestError.IOError)

    return _finalize_staged(staging, file.filename, sha.hexdigest(), store, media_root)


def ingest_bytes(
    data: bytes,
    filename: str,
    store: MediaStore,
    media_root: Path,
    upload_root: Path,
    max_bytes: int,
) -> Result[MediaItem, IngestError]:
    """Ingest an in-memory blob through the same pipeline as handle_upload.

    For callers that already hold the full file (cloud sync). Enforces
    *max_bytes* (FileTooLarge), writes *data* to ``upload_root/filename``
    (OSError -> IOError), then defers to the shared dedup/EXIF/move/index tail.
    """
    if len(data) > max_bytes:
        return Err(IngestError.FileTooLarge)

    staging = upload_root / filename
    try:
        staging.parent.mkdir(parents=True, exist_ok=True)
        with open(staging, "wb") as dest:
            dest.write(data)
    except OSError:
        return Err(IngestError.IOError)

    digest = hashlib.sha256(data).hexdigest()
    return _finalize_staged(staging, filename, digest, store, media_root)


def _finalize_staged(
    staging: Path,
    filename: str,
    digest: str,
    store: MediaStore,
    media_root: Path,
) -> Result[MediaItem, IngestError]:
    """Dedup-check, EXIF-extract, move staging into media_root/YYYY/MM/DD/, index.

    Shared tail of handle_upload and ingest_bytes. Unlinks *staging* on every
    error path (duplicate, rename failure).
    """
    if store.sha256_exists(digest):
        staging.unlink(missing_ok=True)
        return Err(IngestError.DuplicateFile)

    exif_result = extract_exif(staging)
    if exif_result.is_ok:
        meta = exif_result.danger_ok
    else:
        _log.warning(
            "EXIF extraction failed for %s (%s); using minimal metadata",
            filename,
            exif_result.danger_err,
        )
        from malmberg_core.models import MediaMetadata

        meta = MediaMetadata(sha256=digest)

    meta = meta.model_copy(update={"sha256": digest})

    now = datetime.now(timezone.utc)
    rel_path = f"{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
    final = media_root / rel_path
    final.parent.mkdir(parents=True, exist_ok=True)

    try:
        staging.rename(final)
    except OSError:
        staging.unlink(missing_ok=True)
        return Err(IngestError.IOError)

    kind: str = "video" if Path(filename).suffix.lower() in _VIDEO_EXTS else "image"
    item = MediaItem(
        kind=kind,  # type: ignore[arg-type]
        filename=filename,
        server_path=rel_path,
        meta=meta,
    )
    store.add(item)
    _log.info("Ingested %s -> %s (sha256 %s)", filename, rel_path, digest[:12])
    return Ok(item)
