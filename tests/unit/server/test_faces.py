"""Tests for malmberg_server.faces (person index, detection fallback, search)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.api.routes import build_app
from malmberg_server.app.config import ServerConfig
from malmberg_server.faces.detect import detect_faces
from malmberg_server.faces.people import PersonStore
from malmberg_server.ingest.store import MediaStore

# ---------------------------------------------------------------------------
# detect_faces: must degrade gracefully without the `faces` extra
# ---------------------------------------------------------------------------


def test_detect_faces_without_extra_returns_empty(tmp_path: Path, monkeypatch) -> None:
    """When insightface cannot be imported, detect_faces must return []
    rather than raise, regardless of whether the extra happens to be
    installed in the current test environment."""
    import malmberg_server.faces.detect as detect_mod

    monkeypatch.setattr(detect_mod, "_analyzer", False)
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"not a real image")
    assert detect_faces(img, tmp_path / "models") == []


def test_detect_faces_missing_file_returns_empty(tmp_path: Path) -> None:
    """A nonexistent path must never raise -- always degrades to []."""
    assert detect_faces(tmp_path / "nope.jpg", tmp_path / "models") == []


# ---------------------------------------------------------------------------
# PersonStore: online clustering
# ---------------------------------------------------------------------------


def _unit(vec: list[float]) -> list[float]:
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


def test_person_store_clusters_near_embeddings_together() -> None:
    people = PersonStore()
    base = _unit([1.0, 0.0, 0.0, 0.0])
    near = _unit([0.95, 0.05, 0.0, 0.0])

    pid1 = people.assign_face(base, "item-1")
    pid2 = people.assign_face(near, "item-2")

    assert pid1 == pid2
    assert len(people) == 1


def test_person_store_separates_far_embeddings() -> None:
    people = PersonStore()
    a = _unit([1.0, 0.0, 0.0, 0.0])
    b = _unit([0.0, 1.0, 0.0, 0.0])

    pid1 = people.assign_face(a, "item-1")
    pid2 = people.assign_face(b, "item-2")

    assert pid1 != pid2
    assert len(people) == 2


def test_person_store_rename_and_query() -> None:
    people = PersonStore()
    vec = _unit([1.0, 0.2, 0.3, 0.1])
    pid = people.assign_face(vec, "item-1")

    result = people.rename(pid, "Grandma")
    assert result.is_ok
    assert result.danger_ok.name == "Grandma"

    listed = people.list()
    assert listed[0]["id"] == pid
    assert listed[0]["name"] == "Grandma"
    assert listed[0]["sample_item_id"] == "item-1"


def test_person_store_rename_not_found() -> None:
    people = PersonStore()
    result = people.rename("nope", "Someone")
    assert result.is_err


def test_person_store_suggest_and_find_by_name() -> None:
    people = PersonStore()
    pid1 = people.assign_face(_unit([1, 0, 0, 0]), "i1")
    pid2 = people.assign_face(_unit([0, 1, 0, 0]), "i2")
    people.rename(pid1, "Alice")
    people.rename(pid2, "Alicia")

    assert set(people.suggest(q="ali")) == {"Alice", "Alicia"}
    assert people.suggest(q="bob") == []
    assert len(people.find_by_name("alice")) == 1


def test_person_store_persistence(tmp_path: Path) -> None:
    people = PersonStore()
    pid = people.assign_face(_unit([1, 0, 0, 0]), "item-1")
    people.rename(pid, "Bob")

    path = tmp_path / "people.jsonl"
    save = people.save_to_disk(path)
    assert save.is_ok

    reloaded = PersonStore()
    load = reloaded.load_from_disk(path)
    assert load.is_ok
    assert load.danger_ok == 1
    assert reloaded.get(pid).name == "Bob"


# ---------------------------------------------------------------------------
# MediaStore integration: search-by-person and by_person stats
# ---------------------------------------------------------------------------


def _make_item(**kwargs) -> MediaItem:
    defaults = dict(
        kind="image",
        filename="photo.jpg",
        server_path="2024/01/01/photo.jpg",
    )
    defaults.update(kwargs)
    return MediaItem(**defaults)


def test_matches_query_person_name() -> None:
    people = PersonStore()
    pid = people.assign_face(_unit([1, 0, 0, 0]), "item-1")
    people.rename(pid, "Grandma")

    store = MediaStore()
    store.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(sha256="h1"),
            person_ids=[pid],
            faces_processed=True,
        )
    )
    store.add(
        _make_item(
            filename="b.jpg", server_path="p/b.jpg", meta=MediaMetadata(sha256="h2")
        )
    )

    page = store.list(q="grandma", people=people)
    assert page.total == 1
    assert page.items[0].filename == "a.jpg"

    # Without a people store, name matches are simply not attempted.
    page_no_people = store.list(q="grandma")
    assert page_no_people.total == 0


def test_stats_by_person() -> None:
    people = PersonStore()
    pid = people.assign_face(_unit([1, 0, 0, 0]), "item-1")
    people.rename(pid, "Grandma")
    unnamed_pid = people.assign_face(_unit([0, 1, 0, 0]), "item-2")
    assert people.get(unnamed_pid).name is None

    store = MediaStore()
    store.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(sha256="h1"),
            person_ids=[pid],
            faces_processed=True,
        )
    )
    store.add(
        _make_item(
            filename="b.jpg",
            server_path="p/b.jpg",
            meta=MediaMetadata(sha256="h2"),
            person_ids=[unnamed_pid],
            faces_processed=True,
        )
    )

    stats = store.stats(people=people)
    assert stats["by_person"] == {"Grandma": 1}

    # Without a people store, by_person is simply omitted.
    stats_no_people = store.stats()
    assert "by_person" not in stats_no_people


def test_counts_by_person() -> None:
    store = MediaStore()
    store.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(sha256="h1"),
            person_ids=["p1", "p2"],
        )
    )
    store.add(
        _make_item(
            filename="b.jpg",
            server_path="p/b.jpg",
            meta=MediaMetadata(sha256="h2"),
            person_ids=["p1"],
        )
    )
    assert store.counts_by_person() == {"p1": 2, "p2": 1}


def test_pending_face_ids_excludes_processed_and_trashed() -> None:
    from datetime import datetime, timezone

    store = MediaStore()
    store.add(
        _make_item(
            filename="a.jpg", server_path="p/a.jpg", meta=MediaMetadata(sha256="h1")
        )
    )
    store.add(
        _make_item(
            filename="b.jpg",
            server_path="p/b.jpg",
            meta=MediaMetadata(sha256="h2"),
            faces_processed=True,
        )
    )
    store.add(
        _make_item(
            filename="c.jpg",
            server_path="p/c.jpg",
            meta=MediaMetadata(sha256="h3"),
            trashed_at=datetime.now(timezone.utc),
        )
    )
    pending = store.pending_face_ids(10)
    assert len(pending) == 1


# ---------------------------------------------------------------------------
# HTTP endpoints: /people, /people/{id}/name, /people/suggest
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    cfg = ServerConfig(fs_root=tmp_path)
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir()
    return TestClient(build_app(cfg))


def test_people_endpoints_empty(client: TestClient) -> None:
    r = client.get("/people")
    assert r.status_code == 200
    assert r.json() == []

    r = client.get("/people/suggest?q=al")
    assert r.status_code == 200
    assert r.json() == []


def test_people_name_not_found(client: TestClient) -> None:
    r = client.post("/people/nope/name", json={"name": "Someone"})
    assert r.status_code == 404


def test_people_name_requires_nonempty(client: TestClient, tmp_path: Path) -> None:
    # Seed a person directly via the store the app was built with is not
    # accessible from here, so exercise the empty-name validation path only.
    r = client.post("/people/whatever/name", json={"name": "   "})
    assert r.status_code == 400
