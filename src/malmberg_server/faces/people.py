"""PersonStore: people (face clusters), grouped from the per-face index.

A Person is a cluster of same-person faces, optionally named by the user.
The per-face index (`malmberg_server.faces.faces_index.FaceStore`) is the
source of truth for which face belongs to whom and holds the embeddings;
a Person's centroid/count/samples are always *derived* from it and can be
rebuilt at any time (recompute / recluster). Persisted as JSON-lines like
PlaylistStore, at ``fs_root/logs/people.jsonl``.

Grouping quality (see faces/cluster.py for the rationale):
- Online assignment uses single-linkage max-similarity against a person's
  stored face embeddings (not a drifting running-average centroid), at
  `cluster.SIMILARITY_THRESHOLD`.
- `recluster` does an order-independent full rebuild via connected
  components over the whole per-face graph, preserving user-assigned names
  by matching each rebuilt cluster to the old person it mostly inherits.
"""

from __future__ import annotations

import uuid
from collections import Counter
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_server.faces.cluster import (
    SIMILARITY_THRESHOLD,
    centroid,
    connected_components,
    max_similarity,
)
from malmberg_server.faces.faces_index import FaceEntry, FaceStore

_log = get_logger(__name__)

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
    """Centroid (mean) of this person's face embeddings; derived from FaceStore."""
    face_count: int = 0
    """Number of faces currently assigned to this person; derived from FaceStore."""
    sample_item_ids: list[str] = Field(default_factory=list)
    """A handful of item ids this person appears in, for a dashboard thumbnail."""


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
    # Clustering: online assignment + recompute + full recluster
    # ------------------------------------------------------------------

    def assign(
        self,
        faces: FaceStore,
        embedding: list[float],
        bbox: tuple[int, int, int, int],
        det_score: float,
        item_id: str,
    ) -> str:
        """Assign a detected face to a person and record it in *faces*.

        Single-linkage online assignment: the face joins the existing person
        with the highest max-similarity to any of that person's stored faces
        if that similarity is at least `SIMILARITY_THRESHOLD`; otherwise a new
        unnamed person is created. Writes one FaceEntry (with bbox + embedding)
        and refreshes the chosen person's derived centroid/count/samples.
        Returns the (possibly new) person id.
        """
        best_pid: Optional[str] = None
        best_sim = -1.0
        for pid in self._people:
            sim = max_similarity(embedding, faces.embeddings_for_person(pid))
            if sim > best_sim:
                best_sim = sim
                best_pid = pid

        if best_pid is not None and best_sim >= SIMILARITY_THRESHOLD:
            pid = best_pid
            _log.info(
                "Assigned face in %s to person %s (sim=%.3f)", item_id, pid, best_sim
            )
        else:
            person = Person()
            self._people[person.id] = person
            pid = person.id
            _log.info("Created new person %s from face in %s", pid, item_id)

        faces.add(
            FaceEntry(
                item_id=item_id,
                person_id=pid,
                bbox=bbox,
                det_score=det_score,
                embedding=list(embedding),
            )
        )
        self.recompute_person(pid, faces)
        return pid

    def recompute_person(self, person_id: str, faces: FaceStore) -> None:
        """Rebuild *person_id*'s centroid/count/samples from its faces."""
        person = self._people.get(person_id)
        if person is None:
            return
        embs = faces.embeddings_for_person(person_id)
        items = faces.item_ids_for_person(person_id)
        self._people[person_id] = person.model_copy(
            update={
                "embedding": centroid(embs),
                "face_count": len(embs),
                "sample_item_ids": items[:_MAX_SAMPLE_ITEMS],
            }
        )

    def prune_empty(self) -> None:
        """Drop unnamed persons that no longer own any face (named ones stay)."""
        for pid, person in list(self._people.items()):
            if person.face_count == 0 and not person.name:
                del self._people[pid]

    def recompute_all(self, faces: FaceStore) -> None:
        """Rebuild every person from *faces*, then prune empty unnamed persons."""
        for pid in list(self._people):
            self.recompute_person(pid, faces)
        self.prune_empty()

    def recluster(self, faces: FaceStore) -> None:
        """Order-independent full rebuild of person groups from *faces*.

        Runs single-linkage connected components over every stored face
        embedding, then rebuilds the Person set from the resulting clusters.
        User-assigned names are preserved by giving each rebuilt cluster the
        id (and name) of the old person that the plurality of its faces
        previously belonged to (largest cluster wins a contested old id).
        Faces are rewritten in place with their new person id; callers must
        refresh MediaItem.person_ids afterward from the updated FaceStore.
        """
        entries = faces.all()
        if not entries:
            self._people = {}
            return
        embeddings = [e.embedding for e in entries]
        comps = connected_components(embeddings, SIMILARITY_THRESHOLD)
        old_person = {e.face_id: e.person_id for e in entries}
        old_names = {pid: p.name for pid, p in self._people.items()}

        new_people: dict[str, Person] = {}
        used_old: set[str] = set()
        face_new: dict[str, str] = {}

        for comp in sorted(comps, key=len, reverse=True):
            comp_entries = [entries[i] for i in comp]
            counts = Counter(old_person[e.face_id] for e in comp_entries)
            dom: Optional[str] = None
            for pid, _ in counts.most_common():
                if pid not in used_old:
                    dom = pid
                    break
            if dom is not None:
                new_pid = dom
                used_old.add(dom)
                name = old_names.get(dom)
            else:
                new_pid = str(uuid.uuid4())
                name = None
            items: list[str] = []
            for e in comp_entries:
                if e.item_id not in items:
                    items.append(e.item_id)
            new_people[new_pid] = Person(
                id=new_pid,
                name=name,
                embedding=centroid([e.embedding for e in comp_entries]),
                face_count=len(comp_entries),
                sample_item_ids=items[:_MAX_SAMPLE_ITEMS],
            )
            for e in comp_entries:
                face_new[e.face_id] = new_pid

        for face_id, pid in face_new.items():
            faces.set_person(face_id, pid)
        self._people = new_people
        _log.info("Recluster: %d faces -> %d people", len(entries), len(new_people))

    # ------------------------------------------------------------------
    # Manual overrides: create, reassign, merge, rename
    # ------------------------------------------------------------------

    def create_person(self) -> str:
        """Create a new empty, unnamed person and return its id."""
        person = Person()
        self._people[person.id] = person
        return person.id

    def merge(
        self, into_id: str, from_id: str, faces: FaceStore
    ) -> Result[Person, str]:
        """Merge person *from_id* into *into_id*: move its faces, drop it.

        The surviving person keeps *into_id*'s name; its centroid/count are
        recomputed from the combined faces. No-op error if either id is
        unknown or they are the same.
        """
        if into_id == from_id:
            return Err(PersonError.NOT_FOUND)
        if into_id not in self._people or from_id not in self._people:
            return Err(PersonError.NOT_FOUND)
        moved = faces.reassign_all(from_id, into_id)
        del self._people[from_id]
        self.recompute_person(into_id, faces)
        _log.info("Merged person %s into %s (%d faces)", from_id, into_id, moved)
        return Ok(self._people[into_id])

    def rename(self, person_id: str, name: str) -> Result[Person, str]:
        """Assign or change the display name of *person_id*."""
        person = self._people.get(person_id)
        if person is None:
            return Err(PersonError.NOT_FOUND)
        updated = person.model_copy(update={"name": name.strip() or None})
        self._people[person_id] = updated
        _log.info("Named person %s -> %r", person_id, updated.name)
        return Ok(updated)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, person_id: str) -> Optional[Person]:
        """Return the Person with *person_id*, or None if unknown."""
        return self._people.get(person_id)

    def find_by_name(self, needle: str) -> list[Person]:
        """Return named people whose name contains *needle* (case-insensitive)."""
        n = needle.strip().lower()
        if not n:
            return []
        return [p for p in self._people.values() if p.name and n in p.name.lower()]

    def list(
        self,
        counts_by_person: Optional[dict[str, int]] = None,
        *,
        min_count: int = 0,
    ) -> list[dict]:
        """Return people as dicts: id, name, sample thumbnail item id, count.

        *counts_by_person*, if given (person_id -> distinct-photo count from
        the MediaStore), is used as the displayed ``count`` and as the value
        the *min_count* gate compares against; otherwise ``face_count`` is
        used. *min_count* filters out small/uncertain clusters (the dashboard
        hides naming for those but can still fetch them with min_count=1).
        Named people are always included regardless of *min_count* so a named
        person never silently disappears.
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
            if count < min_count and not p.name:
                continue
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
