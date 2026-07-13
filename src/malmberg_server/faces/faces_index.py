"""FaceStore: per-face index (one record per detected face), JSON-lines.

Each detected face gets its own persisted record carrying its bounding box,
its assigned person id, and (crucially, for order-independent re-clustering
and manual overrides) its embedding. Persisted at
``fs_root/logs/faces.jsonl`` like people.jsonl / media-index.jsonl.

This is the source of truth for face -> person membership; PersonStore's
centroids and counts are derived from it and can always be rebuilt (see
PersonStore.recompute / recluster). Keeping embeddings here is what lets the
batch re-cluster and the "reassign / merge" overrides recompute cleanly
instead of trying to subtract from a running-average centroid.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import BaseModel, Field
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger

_log = get_logger(__name__)


class FaceEntry(BaseModel):
    """One detected face: where it is, who it belongs to, and its embedding."""

    face_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str
    """MediaItem id this face was detected in."""
    person_id: str
    """Person id this face is currently assigned to."""
    bbox: tuple[int, int, int, int]
    """(x1, y1, x2, y2) in source-image pixel coordinates, for the green box."""
    det_score: float = 0.0
    """insightface detector confidence for this face (used for QC filtering)."""
    embedding: list[float] = Field(default_factory=list)
    """L2-normalized 512-d ArcFace embedding; persisted so groups can be
    rebuilt from scratch (recluster) and overrides can recompute centroids."""


class FaceStore:
    """In-memory per-face index, persisted to a JSON-lines file."""

    def __init__(self) -> None:
        self._faces: dict[str, FaceEntry] = {}
        self._by_person: dict[str, dict[str, None]] = {}
        self._by_item: dict[str, dict[str, None]] = {}
        """face_ids grouped by person and by item.

        The inner dicts are ordered sets -- dict preserves insertion order and
        gives O(1) add/discard, so a query stays in a stable order without
        having to walk the whole index to recover one.

        Every query here used to scan all faces. That is cheap once, but
        PersonStore.assign asks for a person's embeddings *per person, per new
        face*, which made the worker's sweep quadratic in the size of the face
        index -- the cost lands exactly when a fresh import is being processed
        and the index is at its biggest. Maintained by _put/_forget below.
        """

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_from_disk(self, path: Path) -> Result[int, str]:
        """Populate the in-memory index from *path* (JSON-lines).

        A missing file is treated as an empty store. Returns Ok(n) with the
        number of faces loaded, or Err on parse failure.
        """
        if not path.is_file():
            return Ok(0)
        try:
            loaded = 0
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = FaceEntry.model_validate_json(line)
                    self._put(entry)
                    loaded += 1
            _log.info("Loaded %d faces from %s", loaded, path)
            return Ok(loaded)
        except Exception as exc:
            _log.error("Failed to load faces index from %s: %s", path, exc)
            return Err("storage_error")

    def save_to_disk(self, path: Path) -> Result[None, str]:
        """Write the current in-memory index to *path* atomically."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                for entry in self._faces.values():
                    f.write(entry.model_dump_json())
                    f.write("\n")
            tmp.replace(path)
            return Ok(None)
        except Exception as exc:
            _log.error("Failed to save faces index to %s: %s", path, exc)
            return Err("storage_error")

    # ------------------------------------------------------------------
    # Mutations
    #
    # Every write goes through _put/_forget, which is what keeps _by_person and
    # _by_item honest. Assigning into self._faces anywhere else would desync
    # them silently, and the symptom (a person missing half their photos) would
    # look like a clustering bug, not an indexing one.
    # ------------------------------------------------------------------

    def _put(self, entry: FaceEntry) -> None:
        """Insert or replace *entry*, keeping the person/item indexes in step."""
        old = self._faces.get(entry.face_id)
        if old is not None:
            self._unlink(old)
        self._faces[entry.face_id] = entry
        self._by_person.setdefault(entry.person_id, {})[entry.face_id] = None
        self._by_item.setdefault(entry.item_id, {})[entry.face_id] = None

    def _unlink(self, entry: FaceEntry) -> None:
        """Drop *entry* from the person/item indexes (not from _faces)."""
        person = self._by_person.get(entry.person_id)
        if person is not None:
            person.pop(entry.face_id, None)
            if not person:
                del self._by_person[entry.person_id]
        item = self._by_item.get(entry.item_id)
        if item is not None:
            item.pop(entry.face_id, None)
            if not item:
                del self._by_item[entry.item_id]

    def _forget(self, entry: FaceEntry) -> None:
        """Remove *entry* entirely, keeping the person/item indexes in step."""
        self._faces.pop(entry.face_id, None)
        self._unlink(entry)

    def _entries(self, face_ids: dict[str, None]) -> list[FaceEntry]:
        """Entries for *face_ids*, in the order they joined that person/item."""
        return [self._faces[fid] for fid in face_ids if fid in self._faces]

    def add(self, entry: FaceEntry) -> None:
        """Insert *entry* into the index."""
        self._put(entry)

    def remove_for_item(self, item_id: str) -> list[FaceEntry]:
        """Delete and return all face entries belonging to *item_id*.

        Used by the worker's reprocess path so re-running detection on an
        item does not leave stale/duplicate face records behind.
        """
        removed = self._entries(self._by_item.get(item_id, {}))
        for e in removed:
            self._forget(e)
        return removed

    def remove_for_person(self, person_id: str) -> list[FaceEntry]:
        """Delete and return every face entry assigned to *person_id*.

        Backs "delete this person": the embeddings must go, not just the
        Person record. recluster() rebuilds people from the face index, so a
        person whose faces survived would simply reappear on the next
        recluster. The photos themselves are untouched.
        """
        removed = self._entries(self._by_person.get(person_id, {}))
        for e in removed:
            self._forget(e)
        return removed

    def set_person(self, face_id: str, person_id: str) -> bool:
        """Reassign *face_id* to *person_id*. Returns False if unknown."""
        entry = self._faces.get(face_id)
        if entry is None:
            return False
        self._put(entry.model_copy(update={"person_id": person_id}))
        return True

    def reassign_all(self, from_person: str, to_person: str) -> int:
        """Move every face of *from_person* to *to_person*; return the count."""
        moving = self._entries(self._by_person.get(from_person, {}))
        for entry in moving:
            self._put(entry.model_copy(update={"person_id": to_person}))
        return len(moving)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, face_id: str) -> FaceEntry | None:
        """Return the FaceEntry with *face_id*, or None."""
        return self._faces.get(face_id)

    def all(self) -> list[FaceEntry]:
        """Return every face entry (order stable by insertion)."""
        return list(self._faces.values())

    def embeddings_for_person(self, person_id: str) -> list[list[float]]:
        """Return the stored embeddings of every face assigned to *person_id*."""
        entries = self._entries(self._by_person.get(person_id, {}))
        return [e.embedding for e in entries]

    def faces_for_person(self, person_id: str) -> list[dict]:
        """Return [{face_id, item_id, bbox}, ...] for *person_id*."""
        return [
            {"face_id": e.face_id, "item_id": e.item_id, "bbox": list(e.bbox)}
            for e in self._entries(self._by_person.get(person_id, {}))
        ]

    def faces_for_item(self, item_id: str) -> list[dict]:
        """Return [{face_id, person_id, bbox}, ...] for *item_id*."""
        return [
            {"face_id": e.face_id, "person_id": e.person_id, "bbox": list(e.bbox)}
            for e in self._entries(self._by_item.get(item_id, {}))
        ]

    def person_ids_for_item(self, item_id: str) -> list[str]:
        """Return the distinct person ids present in *item_id* (insertion order)."""
        out: list[str] = []
        for e in self._entries(self._by_item.get(item_id, {})):
            if e.person_id not in out:
                out.append(e.person_id)
        return out

    def item_ids_for_person(self, person_id: str) -> list[str]:
        """Return the distinct item ids *person_id* appears in (insertion order)."""
        out: list[str] = []
        for e in self._entries(self._by_person.get(person_id, {})):
            if e.item_id not in out:
                out.append(e.item_id)
        return out

    def __len__(self) -> int:
        return len(self._faces)
