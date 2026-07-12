"""Tests for manual date/location tagging (POST /media/{id}/tag,
/media/tag-bulk) and the trap this feature must close: manual overrides
must survive MediaStore._refresh_if_stale (schema bump) and the
POST /media/{id}/transform re-extract, and must be wired into search,
stats, and places."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.api.routes import build_app
from malmberg_server.app.config import ServerConfig
from malmberg_server.ingest import media as media_module
from malmberg_server.ingest.store import MediaStore


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    cfg = ServerConfig(fs_root=tmp_path)
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir()
    return TestClient(build_app(cfg))


def _upload_image(client: TestClient, filename: str = "photo.jpg") -> str:
    buf = BytesIO()
    # Vary the pixel color by filename so repeat calls with different
    # filenames produce distinct sha256 digests (upload dedups by content).
    color = (abs(hash(filename)) % 200, 20, 30)
    Image.new("RGB", (100, 60), color).save(buf, "JPEG")
    r = client.post("/upload", files={"file": (filename, buf.getvalue(), "image/jpeg")})
    assert r.status_code == 200
    return r.json()["id"]


# ------------------------------------------------------------------
# Basic set / clear
# ------------------------------------------------------------------


def test_tag_sets_manual_date_and_place(client: TestClient) -> None:
    item_id = _upload_image(client)
    r = client.post(
        f"/media/{item_id}/tag",
        json={"date": "2006-07-04", "place": "Grandma's house, Tampa"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["manual_taken_at"].startswith("2006-07-04")
    assert body["meta"]["manual_place"] == "Grandma's house, Tampa"
    assert body["meta"]["effective_taken_at"].startswith("2006-07-04")
    assert body["meta"]["effective_place"] == "Grandma's house, Tampa"


def test_tag_clear_reverts_to_exif_value(client: TestClient) -> None:
    item_id = _upload_image(client)
    client.post(f"/media/{item_id}/tag", json={"date": "2006-07-04"})
    r = client.post(f"/media/{item_id}/tag", json={"date": None})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["manual_taken_at"] is None
    # The uploaded fake JPEG has no EXIF DateTimeOriginal -> falls back to None.
    assert body["meta"]["effective_taken_at"] is None


def test_tag_partial_update_preserves_other_manual_fields(
    client: TestClient,
) -> None:
    item_id = _upload_image(client)
    client.post(f"/media/{item_id}/tag", json={"date": "2010-01-01"})
    r = client.post(f"/media/{item_id}/tag", json={"place": "Denver"})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["manual_taken_at"].startswith("2010-01-01")
    assert body["meta"]["manual_place"] == "Denver"


def test_tag_not_found(client: TestClient) -> None:
    r = client.post("/media/does-not-exist/tag", json={"date": "2020-01-01"})
    assert r.status_code == 404


def test_tag_invalid_date(client: TestClient) -> None:
    item_id = _upload_image(client)
    r = client.post(f"/media/{item_id}/tag", json={"date": "not-a-date"})
    assert r.status_code == 400


def test_tag_coordinates_reverse_geocode_into_place(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "malmberg_server.api.routes.reverse_geocode",
        lambda lat, lon: "Tampa, Florida, US",
    )
    item_id = _upload_image(client)
    r = client.post(f"/media/{item_id}/tag", json={"lat": 27.9, "lon": -82.4})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["manual_lat"] == 27.9
    assert body["meta"]["manual_lon"] == -82.4
    assert body["meta"]["manual_place"] == "Tampa, Florida, US"
    assert body["meta"]["effective_place"] == "Tampa, Florida, US"


def test_tag_explicit_place_wins_over_derived_place(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "malmberg_server.api.routes.reverse_geocode",
        lambda lat, lon: "Tampa, Florida, US",
    )
    item_id = _upload_image(client)
    r = client.post(
        f"/media/{item_id}/tag",
        json={"lat": 27.9, "lon": -82.4, "place": "Grandma's house"},
    )
    assert r.status_code == 200
    assert r.json()["meta"]["manual_place"] == "Grandma's house"


# ------------------------------------------------------------------
# Bulk tagging
# ------------------------------------------------------------------


def test_tag_bulk_applies_to_many_ids(client: TestClient) -> None:
    ids = [_upload_image(client, f"p{i}.jpg") for i in range(3)]
    r = client.post(
        "/media/tag-bulk",
        json={"ids": ids, "date": "1999-12-31", "place": "Family reunion"},
    )
    assert r.status_code == 200
    data = r.json()
    assert sorted(data["tagged"]) == sorted(ids)
    assert data["failed"] == []
    for item_id in ids:
        info = client.get(f"/media/{item_id}/info").json()
        assert info["meta"]["manual_place"] == "Family reunion"
        assert info["meta"]["manual_taken_at"].startswith("1999-12-31")


def test_tag_bulk_partial_failure_reports_failed_ids(client: TestClient) -> None:
    good_id = _upload_image(client)
    r = client.post(
        "/media/tag-bulk",
        json={"ids": [good_id, "missing-id"], "date": "2001-01-01"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tagged"] == [good_id]
    assert data["failed"] == ["missing-id"]


# ------------------------------------------------------------------
# The trap: manual tags must survive re-extraction and rotation
# ------------------------------------------------------------------


def test_manual_tag_survives_refresh_if_stale(tmp_path: Path) -> None:
    """A stale schema_version triggers _refresh_if_stale to re-extract EXIF
    from the file; the manual override must not be clobbered."""
    media_root = tmp_path / "media"
    media_root.mkdir()
    server_path = "2020/01/01/photo.jpg"
    path = media_root / server_path
    path.parent.mkdir(parents=True)
    Image.new("RGB", (50, 50), (1, 2, 3)).save(path, "JPEG")

    store = MediaStore()
    item = MediaItem(
        kind="image",
        filename="photo.jpg",
        server_path=server_path,
        meta=MediaMetadata(
            sha256="deadbeef",
            schema_version=0,  # force staleness
            manual_taken_at=datetime(2006, 7, 4, tzinfo=timezone.utc),
            manual_place="Grandma's house",
            manual_lat=27.9,
            manual_lon=-82.4,
        ),
    )
    store.add(item)

    refreshed = store.get(item.id, media_root=media_root)
    assert refreshed is not None
    assert refreshed.meta.schema_version == media_module.META_SCHEMA_VERSION
    assert refreshed.meta.manual_taken_at == datetime(2006, 7, 4, tzinfo=timezone.utc)
    assert refreshed.meta.manual_place == "Grandma's house"
    assert refreshed.meta.manual_lat == 27.9
    assert refreshed.meta.manual_lon == -82.4
    assert refreshed.meta.effective_taken_at == datetime(
        2006, 7, 4, tzinfo=timezone.utc
    )
    assert refreshed.meta.effective_place == "Grandma's house"


def test_manual_tag_survives_transform_rotate(client: TestClient) -> None:
    item_id = _upload_image(client)
    tag_r = client.post(
        f"/media/{item_id}/tag",
        json={"date": "2006-07-04", "place": "Grandma's house"},
    )
    assert tag_r.status_code == 200

    rot_r = client.post(f"/media/{item_id}/transform", json={"rotate": 90})
    assert rot_r.status_code == 200
    body = rot_r.json()
    assert body["meta"]["manual_taken_at"].startswith("2006-07-04")
    assert body["meta"]["manual_place"] == "Grandma's house"
    assert body["meta"]["effective_place"] == "Grandma's house"

    # And it's persisted, not just an in-memory response artifact.
    info = client.get(f"/media/{item_id}/info").json()
    assert info["meta"]["manual_place"] == "Grandma's house"


# ------------------------------------------------------------------
# Search / stats / places wiring
# ------------------------------------------------------------------


def test_search_finds_photo_by_manual_year_month_and_place(
    client: TestClient,
) -> None:
    item_id = _upload_image(client)
    client.post(
        f"/media/{item_id}/tag",
        json={"date": "2006-07-04", "place": "Grandma's house, Tampa"},
    )

    r_year = client.get("/media", params={"q": "2006"})
    assert r_year.json()["total"] == 1

    r_month = client.get("/media", params={"q_time": "2006-07"})
    assert r_month.json()["total"] == 1

    r_place = client.get("/media", params={"q_place": "tampa"})
    assert r_place.json()["total"] == 1


def test_stats_count_manual_date_and_place_and_exclude_from_undated(
    client: TestClient,
) -> None:
    dated_id = _upload_image(client, "dated.jpg")
    undated_id = _upload_image(client, "undated.jpg")

    stats_before = client.get("/stats").json()
    assert stats_before["undated"] == 2

    client.post(
        f"/media/{dated_id}/tag",
        json={"date": "2006-07-04", "place": "Grandma's house"},
    )

    stats_after = client.get("/stats").json()
    assert stats_after["undated"] == 1
    assert stats_after["by_year"]["2006"] == 1
    assert stats_after["by_month"]["2006-07"] == 1
    assert stats_after["by_place"]["Grandma's house"] == 1
    assert undated_id  # sanity: the other item stays undated


def test_places_autocomplete_includes_manual_place(client: TestClient) -> None:
    item_id = _upload_image(client)
    client.post(f"/media/{item_id}/tag", json={"place": "Grandma's house, Tampa"})

    r = client.get("/places", params={"q": "grandma"})
    assert r.status_code == 200
    assert r.json() == ["Grandma's house, Tampa"]
