"""Background face-processing walker: fills the per-face index off the request path.

Uploads must return immediately (see ingest.upload.handle_upload) -- face
detection is expensive (a real ML model pass) and must never run inline in an
async request handler. `run_face_worker` is started as a background asyncio
task at server startup (see api.routes.build_app). Each sweep:

1. Picks a batch of items that are unprocessed OR were processed by an older
   FACE_PROCESSING_VERSION (the reprocess / self-heal path -- this is how a
   model or threshold change, or the introduction of the per-face index,
   takes effect over an already-processed library with no manual step).
2. Runs detection for each in a thread executor (event loop stays free),
   removing any stale per-face records for the item first, then assigning
   each detected face to a person and writing a FaceEntry.
3. Once the backlog is drained, runs one order-independent recluster over the
   whole per-face index so the final groups do not depend on ingest order.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from malmberg_core.logging import get_logger
from malmberg_server.faces.detect import detect_faces
from malmberg_server.faces.faces_index import FaceStore
from malmberg_server.faces.people import PersonStore
from malmberg_server.ingest.store import MediaStore

_log = get_logger(__name__)

FACE_PROCESSING_VERSION = 2
"""Version stamped on MediaItem.faces_version once the worker processes an item.

Bump whenever the face pipeline changes in a way that warrants reprocessing
the existing library (new model pack, new thresholds, new per-face index
schema). Items with a lower faces_version are transparently reprocessed on the
next sweep -- no manual re-ingest.

Version history:
  0/1 -> 2: buffalo_l model, QC filtering, per-face index, max-linkage."""

_POLL_INTERVAL_S = 15.0
"""Seconds to sleep between sweeps when there is nothing left to process."""

_BATCH_SIZE = 5
"""Items processed per sweep before yielding back to the poll sleep, so a
large backlog (e.g. first run over an existing library) doesn't starve the
event loop of a chance to serve requests in between batches."""


def _model_root(fs_root: Path) -> Path:
    """Return the directory the insightface model pack is cached under."""
    return fs_root / ".faces" / "models"


def sync_person_ids(store: MediaStore, faces: FaceStore) -> None:
    """Rewrite every item's MediaItem.person_ids from the per-face index.

    The per-face index is the source of truth; this projects it back onto the
    media items so search/stats/filter stay a fast per-item lookup. Called
    after a recluster or any manual override that moves faces between people.
    """
    by_item: dict[str, list[str]] = {}
    for e in faces.all():
        pids = by_item.setdefault(e.item_id, [])
        if e.person_id not in pids:
            pids.append(e.person_id)
    for item_id in store.all_ids():
        item = store.get(item_id)
        if item is None:
            continue
        desired = by_item.get(item_id, [])
        if item.person_ids != desired:
            store.patch(item_id, {"person_ids": desired})


async def _process_one(
    store: MediaStore,
    people: PersonStore,
    faces: FaceStore,
    item_id: str,
    media_root: Path,
    model_root: Path,
) -> bool:
    """Detect and assign faces for one item. Returns True if the item changed."""
    item = store.get(item_id)
    if item is None:
        return False
    path = media_root / item.server_path
    loop = asyncio.get_running_loop()
    # Reprocess-safe: drop any prior face records for this item first so a
    # re-run never leaves stale/duplicate faces behind.
    faces.remove_for_item(item_id)
    if item.kind != "image" or not path.is_file():
        store.patch(
            item_id,
            {
                "faces_processed": True,
                "faces_version": FACE_PROCESSING_VERSION,
                "person_ids": [],
            },
        )
        return True
    detected = await loop.run_in_executor(None, detect_faces, path, model_root)
    person_ids: list[str] = []
    for face in detected:
        pid = people.assign(faces, face.embedding, face.bbox, face.det_score, item_id)
        if pid not in person_ids:
            person_ids.append(pid)
    store.patch(
        item_id,
        {
            "faces_processed": True,
            "faces_version": FACE_PROCESSING_VERSION,
            "person_ids": person_ids,
        },
    )
    _log.info("Processed faces for %s: found %d person(s)", item_id, len(person_ids))
    return True


def _persist(
    store: MediaStore,
    people: PersonStore,
    faces: FaceStore,
    index_path: Path,
    people_path: Path,
    faces_path: Path,
) -> None:
    """Persist all three stores, logging any failure (best-effort)."""
    if store.save_to_disk(index_path).is_err:
        _log.error("Face worker: failed to persist media index")
    if people.save_to_disk(people_path).is_err:
        _log.error("Face worker: failed to persist people index")
    if faces.save_to_disk(faces_path).is_err:
        _log.error("Face worker: failed to persist faces index")


async def run_face_worker(
    store: MediaStore,
    people: PersonStore,
    faces: FaceStore,
    media_root: Path,
    index_path: Path,
    people_path: Path,
    faces_path: Path,
) -> None:
    """Forever: process pending items in batches, then recluster once drained.

    Persists all stores after any sweep that changed something. Runs until the
    enclosing task is cancelled (server shutdown); per-item failures are caught
    (detect_faces never raises) so a single bad file cannot kill the loop.
    """
    _log.info("Face worker started (model cache: %s)", _model_root(media_root.parent))
    dirty_since_recluster = False
    while True:
        try:
            pending = store.pending_face_ids(FACE_PROCESSING_VERSION, _BATCH_SIZE)
            if not pending:
                if dirty_since_recluster:
                    # Backlog drained: one order-independent recluster so the
                    # final groups don't depend on ingest order, then sync
                    # item.person_ids back from the rebuilt per-face index.
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, people.recluster, faces)
                    sync_person_ids(store, faces)
                    _persist(store, people, faces, index_path, people_path, faces_path)
                    dirty_since_recluster = False
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue
            model_root = _model_root(media_root.parent)
            changed = False
            for item_id in pending:
                try:
                    if await _process_one(
                        store, people, faces, item_id, media_root, model_root
                    ):
                        changed = True
                except Exception:
                    _log.warning(
                        "Face worker: unexpected failure on %s", item_id, exc_info=True
                    )
            if changed:
                dirty_since_recluster = True
                people.recompute_all(faces)
                _persist(store, people, faces, index_path, people_path, faces_path)
        except asyncio.CancelledError:
            _log.info("Face worker stopping")
            raise
        except Exception:
            _log.error("Face worker sweep failed unexpectedly", exc_info=True)
            await asyncio.sleep(_POLL_INTERVAL_S)
