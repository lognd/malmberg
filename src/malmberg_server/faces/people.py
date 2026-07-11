"""PersonStore: online-clustered index of detected people, JSON-lines persisted.

Mirrors malmberg_server.ingest.playlists.PlaylistStore: a small in-memory
index, rewritten to disk in full on save. Clustering is intentionally simple
-- this is a personal library of hundreds of photos, not a production face
pipeline -- each new face embedding is compared by cosine similarity against
every existing person's running centroid; it joins the nearest person above
`_SIMILARITY_THRESHOLD`, else a new (unnamed) person is created.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger

_log = get_logger(__name__)

_SIMILARITY_THRESHOLD = 0.5
"""Minimum cosine similarity to a person's centroid to join that person
rather than start a new one. Chosen per the design brief as a reasonable
middle ground for ArcFace embeddings without pulling in a heavier
clustering library."""

_MAX_SAMPLE_ITEMS = 12
"""Cap on Person.sample_item_ids so the record doesn't grow unbounded."""


class PersonError:
    """Marker namespace for PersonStore error kinds (see typani.result.Result)."""

    NOT_FOUND = "not_found"
    STORAGE_ERROR = "storage_error"


class Person(BaseModel):
    """A cluster of same-person face embeddings, optionally named by the user."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: Optional[str] = None
    """User-assigned display name; None until named from the dashboard."""
    embedding: list[float] = Field(default_factory=list)
    """Running-average centroid of all face embeddings assigned to this person."""
    face_count: int = 0
    """Number of faces assigned to this person so far (for the centroid average)."""
    sample_item_ids: list[str] = Field(default_factory=list)
    """A handful of item ids this person appears in, for a dashboard thumbnail."""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of *a* and *b*, or -1.0 if either is empty."""
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return -1.0
    return dot / (norm_a * norm_b)


class PersonStore:
    """In-memory index of Person records, persisted to a JSON-lines file."""

    def __init__(self) -> None:
        self._people: dict[str, Person] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_from_disk(self, path: Path) -> Result[int, str]:
        """Populate the in-memory index from *path* (JSON-lines).

        A missing file is treated as an empty store. Returns Ok(n) with the
        number of people loaded, or Err on parse failure.
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
                    person = Person.model_validate_json(line)
                    self._people[person.id] = person
                    loaded += 1
            _log.info("Loaded %d people from %s", loaded, path)
            return Ok(loaded)
        except Exception as exc:
            _log.error("Failed to load people index from %s: %s", path, exc)
            return Err(PersonError.STORAGE_ERROR)

    def save_to_disk(self, path: Path) -> Result[None, str]:
        """Write the current in-memory index to *path* atomically."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                for person in self._people.values():
                    f.write(person.model_dump_json())
                    f.write("\n")
            tmp.replace(path)
            return Ok(None)
        except Exception as exc:
            _log.error("Failed to save people index to %s: %s", path, exc)
            return Err(PersonError.STORAGE_ERROR)

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def assign_face(self, embedding: list[float], item_id: str) -> str:
        """Assign a detected face *embedding* (seen in *item_id*) to a person.

        Online nearest-centroid clustering: joins the closest existing
        person if its cosine similarity to *embedding* is at least
        `_SIMILARITY_THRESHOLD`, updating that person's running-average
        centroid and sample items; otherwise creates a new unnamed person.
        Returns the (possibly new) person id.
        """
        best_id: Optional[str] = None
        best_sim = -1.0
        for person in self._people.values():
            sim = _cosine_similarity(person.embedding, embedding)
            if sim > best_sim:
                best_sim = sim
                best_id = person.id

        if best_id is not None and best_sim >= _SIMILARITY_THRESHOLD:
            person = self._people[best_id]
            n = person.face_count
            new_centroid = [
                (c * n + e) / (n + 1) for c, e in zip(person.embedding, embedding)
            ]
            sample_ids = person.sample_item_ids
            if item_id not in sample_ids and len(sample_ids) < _MAX_SAMPLE_ITEMS:
                sample_ids = sample_ids + [item_id]
            self._people[best_id] = person.model_copy(
                update={
                    "embedding": new_centroid,
                    "face_count": n + 1,
                    "sample_item_ids": sample_ids,
                }
            )
            _log.info(
                "Assigned face in %s to existing person %s (sim=%.3f)",
                item_id,
                best_id,
                best_sim,
            )
            return best_id

        person = Person(
            embedding=list(embedding), face_count=1, sample_item_ids=[item_id]
        )
        self._people[person.id] = person
        _log.info("Created new person %s from face in %s", person.id, item_id)
        return person.id

    # ------------------------------------------------------------------
    # Mutations / queries
    # ------------------------------------------------------------------

    def rename(self, person_id: str, name: str) -> Result[Person, str]:
        """Assign or change the display name of *person_id*."""
        person = self._people.get(person_id)
        if person is None:
            return Err(PersonError.NOT_FOUND)
        updated = person.model_copy(update={"name": name.strip() or None})
        self._people[person_id] = updated
        _log.info("Named person %s -> %r", person_id, updated.name)
        return Ok(updated)

    def get(self, person_id: str) -> Optional[Person]:
        """Return the Person with *person_id*, or None if unknown."""
        return self._people.get(person_id)

    def find_by_name(self, needle: str) -> list[Person]:
        """Return named people whose name contains *needle* (case-insensitive)."""
        n = needle.strip().lower()
        if not n:
            return []
        return [p for p in self._people.values() if p.name and n in p.name.lower()]

    def list(self, counts_by_person: Optional[dict[str, int]] = None) -> list[dict]:
        """Return people as dicts: id, name, sample thumbnail item id, count.

        *counts_by_person*, if given (person_id -> photo count from the
        MediaStore, which is the source of truth for item associations),
        overrides the `face_count` (raw face detections) with the actual
        distinct-photo count for display; falls back to face_count when
        omitted (e.g. in isolated PersonStore tests).
        """
        out = []
        for p in sorted(
            self._people.values(),
            key=lambda p: (p.name is None, (p.name or "").lower()),
        ):
            count = (
                counts_by_person.get(p.id, 0)
                if counts_by_person is not None
                else p.face_count
            )
            out.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "count": count,
                    "sample_item_id": p.sample_item_ids[0]
                    if p.sample_item_ids
                    else None,
                }
            )
        return out

    def suggest(self, q: str = "", limit: int = 10) -> list[str]:
        """Autocomplete: named-person names containing *q*, capped at *limit*."""
        matches = (
            self.find_by_name(q) if q else [p for p in self._people.values() if p.name]
        )
        names = sorted({p.name for p in matches if p.name})
        return names[:limit]

    def __len__(self) -> int:
        return len(self._people)
