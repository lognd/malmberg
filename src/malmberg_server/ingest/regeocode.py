"""Background sweep that re-geocodes items whose place predates the gazetteer.

Improving the place dataset (see ingest.gazetteer) is worthless if it only
applies to photos ingested afterwards -- the 1,382 photos already mislabeled
"Singapore" are the whole point. This walks the index and recomputes `place`
for every item behind GAZETTEER_VERSION.

It works off the lat/lon already in the index, so it touches no photo files at
all: no decode, no re-hash, no EXIF re-read. That is why this is its own tiny
version counter rather than a MediaMetadata schema bump, which would force a
full re-extract of every file in the library to fix a string.

A user-set ``manual_place`` is never touched -- it wins over ``place`` anyway
(see MediaMetadata.effective_place), and silently rewriting what someone typed
would be the one unforgivable thing to do here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from malmberg_core.logging import get_logger
from malmberg_server.ingest.gazetteer import GAZETTEER_VERSION, reverse_geocode
from malmberg_server.ingest.store import MediaStore

_log = get_logger(__name__)

_IDLE_POLL_S = 300.0
"""Seconds between sweeps once everything is current. Long: this only has
anything to do after a gazetteer bump or a fresh import."""


def stale_ids(store: MediaStore) -> list[str]:
    """Ids whose `place` was geocoded with an older gazetteer.

    Only items that actually have coordinates: without a fix there is nothing
    to geocode, and marking them current would just be noise.
    """
    out: list[str] = []
    for item_id in store.all_ids():
        item = store.get(item_id)
        if item is None or item.meta.geo_version >= GAZETTEER_VERSION:
            continue
        if item.meta.lat is None or item.meta.lon is None:
            continue
        out.append(item_id)
    return out


def regeocode_item(store: MediaStore, item_id: str) -> bool:
    """Recompute one item's `place` from its stored coordinates.

    Returns True if the stored label changed.
    """
    item = store.get(item_id)
    if item is None:
        return False
    place = reverse_geocode(item.meta.lat, item.meta.lon)
    changed = place != item.meta.place
    updates = {"place": place, "geo_version": GAZETTEER_VERSION}
    store.patch(item_id, {"meta": item.meta.model_copy(update=updates)})
    if changed:
        _log.debug("Re-geocoded %s: %r -> %r", item.filename, item.meta.place, place)
    return changed


def regeocode_all(store: MediaStore) -> tuple[int, int]:
    """Re-geocode every stale item. Returns (visited, changed)."""
    pending = stale_ids(store)
    changed = sum(1 for item_id in pending if regeocode_item(store, item_id))
    return len(pending), changed


async def run_regeocode_worker(store: MediaStore, index_path: Path) -> None:
    """Forever: re-geocode stale items, persist if anything moved, then idle."""
    _log.info("Re-geocode worker started (gazetteer version %d)", GAZETTEER_VERSION)
    loop = asyncio.get_running_loop()
    while True:
        try:
            visited, changed = await loop.run_in_executor(None, regeocode_all, store)
            if visited:
                _log.info(
                    "Re-geocoded %d item(s); %d place label(s) changed",
                    visited,
                    changed,
                )
                if store.save_to_disk(index_path).is_err:
                    _log.error("Failed to persist media index after re-geocode")
            await asyncio.sleep(_IDLE_POLL_S)
        except asyncio.CancelledError:
            _log.info("Re-geocode worker stopping")
            raise
        except Exception:
            _log.error("Re-geocode sweep failed unexpectedly", exc_info=True)
            await asyncio.sleep(_IDLE_POLL_S)


__all__ = [
    "regeocode_all",
    "regeocode_item",
    "run_regeocode_worker",
    "stale_ids",
]
