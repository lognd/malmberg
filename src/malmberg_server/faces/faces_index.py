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
                    self._faces[entry.face_id] = entry
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
    # ------------------------------------------------------------------

    def add(self, entry: FaceEntry) -> None:
        """Insert *entry* into the index."""
        self._faces[entry.face_id] = entry

    def remove_for_item(self, item_id: str) -> list[FaceEntry]:
        """Delete and return all face entries belonging to *item_id*.

        Used by the worker's reprocess path so re-running detection on an
        item does not leave stale/duplicate face records behind.
        """
        removed = [e for e in self._faces.values() if e.item_id == item_id]
        for e in removed:
            del self._faces[e.face_id]
        return removed

    def set_person(self, face_id: str, person_id: str) -> bool:
        """Reassign *face_id* to *person_id*. Returns False if unknown."""
        entry = self._faces.get(face_id)
        if entry is None:
            return False
        self._faces[face_id] = entry.model_copy(update={"person_id": person_id})
        return True

    def reassign_all(self, from_person: str, to_person: str) -> int:
        """Move every face of *from_person* to *to_person*; return the count."""
        moved = 0
        for face_id, entry in list(self._faces.items()):
            if entry.person_id == from_person:
                self._faces[face_id] = entry.model_copy(update={"person_id": to_person})
                moved += 1
        return moved

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
        return [e.embedding for e in self._faces.values() if e.person_id == person_id]

    def faces_for_person(self, person_id: str) -> list[dict]:
        """Return [{face_id, item_id, bbox}, ...] for *person_id*."""
        return [
            {"face_id": e.face_id, "item_id": e.item_id, "bbox": list(e.bbox)}
            for e in self._faces.values()
            if e.person_id == person_id
        ]

    def faces_for_item(self, item_id: str) -> list[dict]:
        """Return [{face_id, person_id, bbox}, ...] for *item_id*."""
        return [
            {"face_id": e.face_id, "person_id": e.person_id, "bbox": list(e.bbox)}
            for e in self._faces.values()
            if e.item_id == item_id
        ]

    def person_ids_for_item(self, item_id: str) -> list[str]:
        """Return the distinct person ids present in *item_id* (insertion order)."""
        out: list[str] = []
        for e in self._faces.values():
            if e.item_id == item_id and e.person_id not in out:
                out.append(e.person_id)
        return out

    def item_ids_for_person(self, person_id: str) -> list[str]:
        """Return the distinct item ids *person_id* appears in (insertion order)."""
        out: list[str] = []
        for e in self._faces.values():
            if e.person_id == person_id and e.item_id not in out:
                out.append(e.item_id)
        return out

    def __len__(self) -> int:
        return len(self._faces)
