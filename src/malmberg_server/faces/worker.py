"""Background face-processing walker: fills in person_ids off the request path.

Uploads must return immediately (see ingest.upload.handle_upload) -- face
detection is expensive (a real ML model pass) and must never run inline in
an async request handler. This module's `run_face_worker` is started as a
background asyncio task at server startup (see api.routes.build_app) and
periodically walks the MediaStore for items with `faces_processed == False`,
running detection in a thread executor so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from malmberg_core.logging import get_logger
from malmberg_server.faces.detect import detect_faces
from malmberg_server.faces.people import PersonStore
from malmberg_server.ingest.store import MediaStore

_log = get_logger(__name__)

_POLL_INTERVAL_S = 15.0
"""Seconds to sleep between sweeps when there is nothing left to process."""

_BATCH_SIZE = 5
"""Items processed per sweep before yielding back to the poll sleep, so a
large backlog (e.g. first run over an existing library) doesn't starve the
event loop of a chance to serve requests in between batches."""


def _model_root(fs_root: Path) -> Path:
    """Return the directory the insightface model pack is cached under."""
    return fs_root / ".faces" / "models"


async def _process_one(
    store: MediaStore,
    people: PersonStore,
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
    if item.kind != "image" or not path.is_file():
        store.patch(item_id, {"faces_processed": True})
        return True
    faces = await loop.run_in_executor(None, detect_faces, path, model_root)
    person_ids: list[str] = []
    for face in faces:
        pid = people.assign_face(face.embedding, item_id)
        if pid not in person_ids:
            person_ids.append(pid)
    store.patch(item_id, {"faces_processed": True, "person_ids": person_ids})
    _log.info("Processed faces for %s: found %d person(s)", item_id, len(person_ids))
    return True


async def run_face_worker(
    store: MediaStore,
    people: PersonStore,
    media_root: Path,
    index_path: Path,
    people_path: Path,
) -> None:
    """Forever: process unprocessed items in small batches, then sleep.

    Persists both stores to disk after any sweep that changed something.
    Runs until the enclosing task is cancelled (server shutdown); any
    per-item failure is caught inside `_process_one`'s callees (detect_faces
    never raises) so a single bad file cannot kill the worker loop.
    """
    _log.info("Face worker started (model cache: %s)", _model_root(media_root.parent))
    while True:
        try:
            pending = store.pending_face_ids(_BATCH_SIZE)
            if not pending:
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue
            model_root = _model_root(media_root.parent)
            changed = False
            for item_id in pending:
                try:
                    item_changed = await _process_one(
                        store, people, item_id, media_root, model_root
                    )
                    if item_changed:
                        changed = True
                except Exception:
                    _log.warning(
                        "Face worker: unexpected failure on %s", item_id, exc_info=True
                    )
            if changed:
                save = store.save_to_disk(index_path)
                if save.is_err:
                    _log.error("Face worker: failed to persist media index")
                save = people.save_to_disk(people_path)
                if save.is_err:
                    _log.error("Face worker: failed to persist people index")
        except asyncio.CancelledError:
            _log.info("Face worker stopping")
            raise
        except Exception:
            _log.error("Face worker sweep failed unexpectedly", exc_info=True)
            await asyncio.sleep(_POLL_INTERVAL_S)
