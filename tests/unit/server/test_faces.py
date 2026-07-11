"""Tests for malmberg_server.faces: clustering, per-face index, overrides, endpoints.

All ML is stubbed -- detect_faces is monkeypatched to return synthetic
FaceRecords, so nothing here needs the `faces` extra (no insightface / numpy).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.api.routes import build_app
from malmberg_server.app.config import ServerConfig
from malmberg_server.faces import worker as worker_mod
from malmberg_server.faces.cluster import (
    connected_components,
    cosine_similarity,
    max_similarity,
)
from malmberg_server.faces.detect import FaceRecord, detect_faces
from malmberg_server.faces.faces_index import FaceEntry, FaceStore
from malmberg_server.faces.people import Person, PersonStore
from malmberg_server.ingest.store import MediaStore


def _unit(vec: list[float]) -> list[float]:
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


def _assign(people: PersonStore, faces: FaceStore, emb: list[float], item: str) -> str:
    """Assign a synthetic face embedding to a person via the store API."""
    return people.assign(faces, emb, (0, 0, 10, 10), 0.99, item)


# ---------------------------------------------------------------------------
# cluster primitives
# ---------------------------------------------------------------------------


def test_cosine_similarity_basics() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1]) == -1.0


def test_max_similarity_picks_best() -> None:
    e = _unit([1, 0, 0])
    cands = [_unit([0, 1, 0]), _unit([0.9, 0.1, 0])]
    assert max_similarity(e, cands) == pytest.approx(cosine_similarity(e, cands[1]))
    assert max_similarity(e, []) == -1.0


def test_connected_components_single_linkage() -> None:
    a = _unit([1, 0, 0, 0])
    b = _unit([0.95, 0.05, 0, 0])
    c = _unit([0, 0, 1, 0])
    comps = connected_components([a, b, c], threshold=0.4)
    assert sorted(len(g) for g in comps) == [1, 2]


def test_connected_components_chain_merges() -> None:
    a = _unit([1, 0, 0])
    b = _unit([0.6, 0.8, 0])
    c = _unit([0, 1, 0])
    comps = connected_components([a, b, c], threshold=0.4)
    assert len(comps) == 1


# ---------------------------------------------------------------------------
# detect_faces graceful degradation (no `faces` extra)
# ---------------------------------------------------------------------------


def test_detect_faces_without_extra_returns_empty(tmp_path: Path, monkeypatch) -> None:
    import malmberg_server.faces.detect as detect_mod

    monkeypatch.setattr(detect_mod, "_analyzer", False)
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"not a real image")
    assert detect_faces(img, tmp_path / "models") == []


def test_detect_faces_missing_file_returns_empty(tmp_path: Path) -> None:
    assert detect_faces(tmp_path / "nope.jpg", tmp_path / "models") == []


# ---------------------------------------------------------------------------
# FaceStore
# ---------------------------------------------------------------------------


def test_face_store_queries_and_persistence(tmp_path: Path) -> None:
    faces = FaceStore()
    faces.add(
        FaceEntry(item_id="i1", person_id="p1", bbox=(1, 2, 3, 4), embedding=[1.0])
    )
    faces.add(
        FaceEntry(item_id="i1", person_id="p2", bbox=(5, 6, 7, 8), embedding=[0.0])
    )
    faces.add(
        FaceEntry(item_id="i2", person_id="p1", bbox=(0, 0, 1, 1), embedding=[1.0])
    )

    assert {f["person_id"] for f in faces.faces_for_item("i1")} == {"p1", "p2"}
    assert faces.person_ids_for_item("i1") == ["p1", "p2"]
    assert sorted(faces.item_ids_for_person("p1")) == ["i1", "i2"]
    assert len(faces.faces_for_person("p1")) == 2

    path = tmp_path / "faces.jsonl"
    assert faces.save_to_disk(path).is_ok
    reloaded = FaceStore()
    assert reloaded.load_from_disk(path).danger_ok == 3
    assert reloaded.person_ids_for_item("i1") == ["p1", "p2"]


def test_face_store_remove_for_item() -> None:
    faces = FaceStore()
    faces.add(FaceEntry(item_id="i1", person_id="p1", bbox=(0, 0, 1, 1)))
    faces.add(FaceEntry(item_id="i2", person_id="p1", bbox=(0, 0, 1, 1)))
    removed = faces.remove_for_item("i1")
    assert len(removed) == 1
    assert len(faces) == 1


# ---------------------------------------------------------------------------
# PersonStore: online assignment (max-linkage) + recompute
# ---------------------------------------------------------------------------


def test_assign_clusters_near_and_separates_far() -> None:
    people, faces = PersonStore(), FaceStore()
    base = _unit([1, 0, 0, 0])
    near = _unit([0.95, 0.05, 0, 0])
    far = _unit([0, 1, 0, 0])

    p1 = _assign(people, faces, base, "i1")
    p2 = _assign(people, faces, near, "i2")
    p3 = _assign(people, faces, far, "i3")

    assert p1 == p2
    assert p3 != p1
    assert len(people) == 2
    assert people.get(p1).face_count == 2


def test_recompute_and_prune_empty() -> None:
    people, faces = PersonStore(), FaceStore()
    pid = _assign(people, faces, _unit([1, 0, 0]), "i1")
    faces.remove_for_item("i1")
    people.recompute_all(faces)
    assert people.get(pid) is None
    assert len(people) == 0


# ---------------------------------------------------------------------------
# Recluster (order-independent) preserves names
# ---------------------------------------------------------------------------


def test_recluster_merges_oversplit_and_keeps_name() -> None:
    people, faces = PersonStore(), FaceStore()
    a = _unit([1, 0, 0, 0])
    b = _unit([0.96, 0.02, 0.01, 0])
    faces.add(FaceEntry(item_id="i1", person_id="pA", bbox=(0, 0, 1, 1), embedding=a))
    faces.add(FaceEntry(item_id="i2", person_id="pB", bbox=(0, 0, 1, 1), embedding=b))
    people._people["pA"] = Person(id="pA", name="Grandma", face_count=1)
    people._people["pB"] = Person(id="pB", face_count=1)

    people.recluster(faces)

    assert len(people) == 1
    surviving = next(iter(people._people.values()))
    assert surviving.name == "Grandma"
    assert surviving.face_count == 2
    assert len(faces.faces_for_person(surviving.id)) == 2


def test_recluster_splits_distinct_people() -> None:
    people, faces = PersonStore(), FaceStore()
    a = _unit([1, 0, 0, 0])
    b = _unit([0, 1, 0, 0])
    faces.add(FaceEntry(item_id="i1", person_id="p0", bbox=(0, 0, 1, 1), embedding=a))
    faces.add(FaceEntry(item_id="i2", person_id="p0", bbox=(0, 0, 1, 1), embedding=b))
    people._people["p0"] = Person(id="p0", face_count=2)
    people.recluster(faces)
    assert len(people) == 2


# ---------------------------------------------------------------------------
# Manual overrides: reassign + merge
# ---------------------------------------------------------------------------


def test_merge_people() -> None:
    people, faces = PersonStore(), FaceStore()
    p1 = _assign(people, faces, _unit([1, 0, 0]), "i1")
    p2 = _assign(people, faces, _unit([0, 1, 0]), "i2")
    people.rename(p1, "Alice")

    result = people.merge(p1, p2, faces)
    assert result.is_ok
    assert people.get(p2) is None
    assert people.get(p1).face_count == 2
    assert people.get(p1).name == "Alice"


def test_merge_unknown_person() -> None:
    people, faces = PersonStore(), FaceStore()
    p1 = _assign(people, faces, _unit([1, 0, 0]), "i1")
    assert people.merge(p1, "nope", faces).is_err
    assert people.merge(p1, p1, faces).is_err


# ---------------------------------------------------------------------------
# rename_with_dedup: name-collision merge
# ---------------------------------------------------------------------------


def test_rename_dedup_exact_case_merges() -> None:
    people, faces = PersonStore(), FaceStore()
    p1 = _assign(people, faces, _unit([1, 0, 0]), "i1")
    p2 = _assign(people, faces, _unit([0, 1, 0]), "i2")
    people.rename(p1, "Alice")

    result = people.rename_with_dedup(p2, "Alice", faces)
    assert result.is_ok
    assert result.danger_ok.id == p1
    assert people.get(p2) is None
    assert people.get(p1).face_count == 2


def test_rename_dedup_different_case_merges() -> None:
    people, faces = PersonStore(), FaceStore()
    p1 = _assign(people, faces, _unit([1, 0, 0]), "i1")
    p2 = _assign(people, faces, _unit([0, 1, 0]), "i2")
    people.rename(p1, "Alice")

    result = people.rename_with_dedup(p2, "  alice  ", faces)
    assert result.is_ok
    assert result.danger_ok.id == p1
    assert people.get(p2) is None


def test_rename_dedup_typo_merges() -> None:
    people, faces = PersonStore(), FaceStore()
    p1 = _assign(people, faces, _unit([1, 0, 0]), "i1")
    p2 = _assign(people, faces, _unit([0, 1, 0]), "i2")
    people.rename(p1, "Alice")

    result = people.rename_with_dedup(p2, "Alicee", faces)
    assert result.is_ok
    assert result.danger_ok.id == p1
    assert people.get(p2) is None


def test_rename_dedup_new_name_does_not_merge() -> None:
    people, faces = PersonStore(), FaceStore()
    p1 = _assign(people, faces, _unit([1, 0, 0]), "i1")
    p2 = _assign(people, faces, _unit([0, 1, 0]), "i2")
    people.rename(p1, "Alice")

    result = people.rename_with_dedup(p2, "Bob", faces)
    assert result.is_ok
    assert result.danger_ok.id == p2
    assert result.danger_ok.name == "Bob"
    assert people.get(p1) is not None
    assert people.get(p1).name == "Alice"


# ---------------------------------------------------------------------------
# min_count gate
# ---------------------------------------------------------------------------


def test_list_min_count_hides_small_but_keeps_named() -> None:
    people, faces = PersonStore(), FaceStore()
    big = _assign(people, faces, _unit([1, 0, 0]), "i1")
    _assign(people, faces, _unit([0.98, 0.02, 0]), "i2")
    _assign(people, faces, _unit([0.99, 0.01, 0]), "i3")
    small = _assign(people, faces, _unit([0, 1, 0]), "i4")
    people.rename(small, "Tiny")

    counts = {big: 3, small: 1}
    ids = {p["id"] for p in people.list(counts, min_count=3)}
    assert big in ids
    assert small in ids  # named -> always shown

    people.rename(small, "")  # clear name
    assert small not in {p["id"] for p in people.list(counts, min_count=3)}
    assert small in {p["id"] for p in people.list(counts, min_count=1)}


# ---------------------------------------------------------------------------
# Worker pipeline (real worker functions, stubbed detect_faces)
# ---------------------------------------------------------------------------


def _make_item(item_id: str, **kwargs) -> MediaItem:
    defaults = dict(
        id=item_id,
        kind="image",
        filename=f"{item_id}.jpg",
        server_path=f"p/{item_id}.jpg",
        meta=MediaMetadata(sha256=item_id, width=100, height=100),
    )
    defaults.update(kwargs)
    return MediaItem(**defaults)


def test_worker_process_one_populates_faces(tmp_path: Path, monkeypatch) -> None:
    store, people, faces = MediaStore(), PersonStore(), FaceStore()
    media_root = tmp_path / "media"
    (media_root / "p").mkdir(parents=True)
    (media_root / "p" / "i1.jpg").write_bytes(b"x")
    store.add(_make_item("i1"))

    emb = _unit([1, 0, 0, 0])
    monkeypatch.setattr(
        worker_mod,
        "detect_faces",
        lambda path, model_root: [
            FaceRecord(bbox=(1, 2, 3, 4), embedding=emb, det_score=0.9)
        ],
    )

    asyncio.run(
        worker_mod._process_one(
            store, people, faces, "i1", media_root, tmp_path / "models"
        )
    )

    item = store.get("i1")
    assert item.faces_processed is True
    assert item.faces_version == worker_mod.FACE_PROCESSING_VERSION
    assert len(item.person_ids) == 1
    assert len(faces) == 1
    assert faces.all()[0].bbox == (1, 2, 3, 4)


def test_worker_reprocess_replaces_stale_faces(tmp_path: Path, monkeypatch) -> None:
    store, people, faces = MediaStore(), PersonStore(), FaceStore()
    media_root = tmp_path / "media"
    (media_root / "p").mkdir(parents=True)
    (media_root / "p" / "i1.jpg").write_bytes(b"x")
    store.add(_make_item("i1"))
    faces.add(FaceEntry(item_id="i1", person_id="old", bbox=(9, 9, 9, 9)))

    monkeypatch.setattr(
        worker_mod,
        "detect_faces",
        lambda path, model_root: [
            FaceRecord(bbox=(1, 1, 2, 2), embedding=_unit([1, 0]), det_score=0.9)
        ],
    )

    asyncio.run(
        worker_mod._process_one(
            store, people, faces, "i1", media_root, tmp_path / "models"
        )
    )
    assert len(faces) == 1
    assert faces.all()[0].bbox == (1, 1, 2, 2)


def test_sync_person_ids_projects_faces_onto_items() -> None:
    store, faces = MediaStore(), FaceStore()
    store.add(_make_item("i1"))
    faces.add(FaceEntry(item_id="i1", person_id="pX", bbox=(0, 0, 1, 1)))
    faces.add(FaceEntry(item_id="i1", person_id="pY", bbox=(0, 0, 1, 1)))
    worker_mod.sync_person_ids(store, faces)
    assert store.get("i1").person_ids == ["pX", "pY"]


def test_pending_face_ids_respects_version() -> None:
    store = MediaStore()
    store.add(_make_item("new"))
    store.add(_make_item("old", faces_processed=True, faces_version=1))
    store.add(_make_item("cur", faces_processed=True, faces_version=2))
    assert set(store.pending_face_ids(2, 10)) == {"new", "old"}


# ---------------------------------------------------------------------------
# MediaStore search / stats by person
# ---------------------------------------------------------------------------


def test_matches_query_and_stats_by_person() -> None:
    people, faces = PersonStore(), FaceStore()
    pid = _assign(people, faces, _unit([1, 0, 0]), "i1")
    people.rename(pid, "Grandma")

    store = MediaStore()
    store.add(_make_item("a", person_ids=[pid], faces_processed=True))
    store.add(_make_item("b"))

    page = store.list(q="grandma", people=people)
    assert page.total == 1 and page.items[0].id == "a"
    assert store.list(q="grandma").total == 0

    stats = store.stats(people=people)
    assert stats["by_person"] == {"Grandma": 1}
    assert "by_person" not in store.stats()


def test_counts_by_person() -> None:
    store = MediaStore()
    store.add(_make_item("a", person_ids=["p1", "p2"]))
    store.add(_make_item("b", person_ids=["p1"]))
    assert store.counts_by_person() == {"p1": 2, "p2": 1}


# ---------------------------------------------------------------------------
# HTTP endpoints (pre-seeded people/faces stores)
# ---------------------------------------------------------------------------


def _seeded_client(tmp_path: Path):
    """A TestClient over an app pre-seeded with two people and their faces."""
    cfg = ServerConfig(fs_root=tmp_path)
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir()
    store, people, faces = MediaStore(), PersonStore(), FaceStore()
    p_grandma = _assign(people, faces, _unit([1, 0, 0]), "i1")
    _assign(people, faces, _unit([0.98, 0.02, 0]), "i2")
    _assign(people, faces, _unit([0.99, 0.01, 0]), "i3")
    people.rename(p_grandma, "Grandma")
    p_small = _assign(people, faces, _unit([0, 1, 0]), "i4")
    store.add(_make_item("i1", person_ids=[p_grandma]))
    store.add(_make_item("i2", person_ids=[p_grandma]))
    store.add(_make_item("i3", person_ids=[p_grandma]))
    store.add(_make_item("i4", person_ids=[p_small]))
    client = TestClient(build_app(cfg, store, people, faces))
    return client, p_grandma, p_small


def test_endpoint_people_min_count(tmp_path: Path) -> None:
    client, p_grandma, p_small = _seeded_client(tmp_path)
    ids = {p["id"] for p in client.get("/people").json()}
    assert p_grandma in ids
    assert p_small not in ids
    ids_all = {p["id"] for p in client.get("/people?min_count=1").json()}
    assert p_small in ids_all


def test_endpoint_person_photos(tmp_path: Path) -> None:
    client, p_grandma, _ = _seeded_client(tmp_path)
    photos = client.get(f"/people/{p_grandma}/photos").json()
    assert len(photos) == 3
    row = photos[0]
    assert set(row) == {"item_id", "face_id", "bbox", "img_w", "img_h"}
    assert row["img_w"] == 100 and row["img_h"] == 100
    assert client.get("/people/nope/photos").status_code == 404


def test_endpoint_reassign_face_detach(tmp_path: Path) -> None:
    client, p_grandma, _ = _seeded_client(tmp_path)
    photos = client.get(f"/people/{p_grandma}/photos").json()
    face_id = photos[0]["face_id"]
    r = client.post(f"/faces/{face_id}/reassign", json={"person_id": None})
    assert r.status_code == 200
    assert r.json()["person_id"] != p_grandma
    assert len(client.get(f"/people/{p_grandma}/photos").json()) == 2
    assert client.post("/faces/nope/reassign", json={}).status_code == 404


def test_endpoint_reassign_face_to_existing(tmp_path: Path) -> None:
    client, p_grandma, p_small = _seeded_client(tmp_path)
    photos = client.get(f"/people/{p_small}/photos").json()
    face_id = photos[0]["face_id"]
    r = client.post(f"/faces/{face_id}/reassign", json={"person_id": p_grandma})
    assert r.status_code == 200
    assert len(client.get(f"/people/{p_grandma}/photos").json()) == 4


def test_endpoint_merge_people(tmp_path: Path) -> None:
    client, p_grandma, p_small = _seeded_client(tmp_path)
    r = client.post(f"/people/{p_grandma}/merge", json={"from_id": p_small})
    assert r.status_code == 200
    assert len(client.get(f"/people/{p_grandma}/photos").json()) == 4
    assert client.get(f"/people/{p_small}/photos").status_code == 404


def test_endpoint_recluster(tmp_path: Path) -> None:
    client, _, _ = _seeded_client(tmp_path)
    r = client.post("/people/recluster")
    assert r.status_code == 200
    assert r.json()["status"] == "reclustered"


def test_endpoint_people_name_validation(tmp_path: Path) -> None:
    client, p_grandma, _ = _seeded_client(tmp_path)
    assert client.post("/people/nope/name", json={"name": "X"}).status_code == 404
    assert (
        client.post(f"/people/{p_grandma}/name", json={"name": "  "}).status_code == 400
    )
    ok = client.post(f"/people/{p_grandma}/name", json={"name": "Nana"})
    assert ok.status_code == 200 and ok.json()["name"] == "Nana"
