"""Background thumbnail warmer: pre-generate the sizes the dashboard browses at.

Thumbnails are generated lazily by GET /media/{id}/thumb on first request. That
is fine once, but it puts a full-resolution decode (a 12 MP HEIC, a video poster
frame) on the request path of whoever turns the page first -- so paging through
the library is slow exactly when a person is sitting there watching it.

This worker walks the library off the request path and writes the missing
thumbnails ahead of time, so the dashboard grid and the next page it prefetches
are served straight off disk. The cache is keyed by file existence, not by any
index state: a thumbnail that is already on disk is skipped, a deleted one is
simply regenerated. Cheap to re-run and safe to interrupt.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from malmberg_core.logging import get_logger
from malmberg_server.ingest.media import make_thumbnail
from malmberg_server.ingest.store import MediaStore

_log = get_logger(__name__)

WARM_SIZES: tuple[int, ...] = (200, 400)
"""Thumbnail sizes to pre-generate, matching what the dashboard requests.

400 is the browse grid's default and the face-review card; 200 is the people
cards and the frame preview strip. The larger sizes (the 1200 face zoom) stay
lazy -- they are opened one photo at a time, not a gridful at once, so warming
them would cost a full decode per item for a request that mostly never comes.
"""

_BATCH_SIZE = 8
"""Items per sweep. Each item is a full-resolution decode per missing size, so
this is deliberately small: the warmer must never starve the request path or
the face worker of the server's cores."""

_IDLE_POLL_S = 60.0
"""Seconds to wait after the backlog drains before looking for new items."""

_BATCH_PAUSE_S = 0.2
"""Breather between batches, so a 17k-item cold start stays a background hum
rather than pinning every core for an hour."""


def thumb_path(fs_root: Path, item_id: str, size: int) -> Path:
    """Path of the cached thumbnail for *item_id* at *size*.

    The one place this layout is spelled out; the /media/{id}/thumb route and
    the permanent-delete cleanup both derive from it.
    """
    return fs_root / ".thumbs" / f"{item_id}_{size}.jpg"


def existing_thumbs(fs_root: Path) -> set[str]:
    """Filenames already in the thumbnail cache.

    One directory listing, rather than a stat() per item per size. The sweep
    runs every minute against 20k items and 2 sizes, so the naive form was
    40,000 filesystem round-trips a minute at idle -- on a spinning NAS, for
    the privilege of learning that there is nothing to do.
    """
    thumbs_dir = fs_root / ".thumbs"
    if not thumbs_dir.is_dir():
        return set()
    return {entry.name for entry in thumbs_dir.iterdir() if entry.is_file()}


def missing_thumbs(store: MediaStore, fs_root: Path) -> list[tuple[str, int]]:
    """Return (item_id, size) pairs that have no cached thumbnail yet.

    Trashed items are skipped: they are not browsable, and warming them would
    re-fill the cache for photos the user just deleted.
    """
    have = existing_thumbs(fs_root)
    out: list[tuple[str, int]] = []
    for item_id in store.all_ids():
        item = store.get(item_id)
        if item is None or item.trashed_at is not None:
            continue
        for size in WARM_SIZES:
            if thumb_path(fs_root, item_id, size).name not in have:
                out.append((item_id, size))
    return out


def _warm_one(
    store: MediaStore, fs_root: Path, media_root: Path, item_id: str, size: int
) -> bool:
    """Generate one thumbnail. Returns True if a file was written."""
    item = store.get(item_id)
    if item is None:
        return False
    src = media_root / item.server_path
    if not src.is_file():
        _log.debug("Thumb warmer: %s has no file on disk, skipping", item_id)
        return False
    dest = thumb_path(fs_root, item_id, size)
    result = make_thumbnail(src, dest, size, is_video=item.kind == "video")
    if result.is_err:
        _log.warning(
            "Thumb warmer: could not thumbnail %s at %d (%s)",
            item.filename,
            size,
            result.danger_err,
        )
        return False
    return True


async def run_thumb_worker(store: MediaStore, fs_root: Path, media_root: Path) -> None:
    """Forever: fill in missing thumbnails in small batches, then idle.

    Runs until the enclosing task is cancelled (server shutdown). Per-item
    failures are logged and skipped -- one undecodable file must not stall the
    warm-up for the whole library.
    """
    _log.info("Thumb warmer started (sizes: %s)", ", ".join(str(s) for s in WARM_SIZES))
    loop = asyncio.get_running_loop()
    while True:
        try:
            pending = await loop.run_in_executor(None, missing_thumbs, store, fs_root)
            if not pending:
                await asyncio.sleep(_IDLE_POLL_S)
                continue
            _log.info("Thumb warmer: %d thumbnail(s) to generate", len(pending))
            written = 0
            for i in range(0, len(pending), _BATCH_SIZE):
                batch = pending[i : i + _BATCH_SIZE]
                for item_id, size in batch:
                    try:
                        if await loop.run_in_executor(
                            None, _warm_one, store, fs_root, media_root, item_id, size
                        ):
                            written += 1
                    except Exception:
                        _log.warning(
                            "Thumb warmer: unexpected failure on %s at %d",
                            item_id,
                            size,
                            exc_info=True,
                        )
                await asyncio.sleep(_BATCH_PAUSE_S)
            _log.info("Thumb warmer: wrote %d thumbnail(s)", written)
        except asyncio.CancelledError:
            _log.info("Thumb warmer stopping")
            raise
        except Exception:
            _log.error("Thumb warmer sweep failed unexpectedly", exc_info=True)
            await asyncio.sleep(_IDLE_POLL_S)
