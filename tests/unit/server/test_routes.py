"""Tests for malmberg_server.api.routes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from malmberg_server.api.routes import build_app
from malmberg_server.app.config import ServerConfig


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    cfg = ServerConfig(fs_root=tmp_path)
    # Create required subdirectories.
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir()
    return TestClient(build_app(cfg))


def test_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "server"
    assert data["version"]
    assert ":" in data["mac"]


def test_status(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "running"
    assert data["uptime_s"] >= 0


def test_version(client: TestClient) -> None:
    r = client.get("/version")
    assert r.status_code == 200
    data = r.json()
    assert data["malmberg_version"]
    assert data["python_version"]
    assert data["platform"]
    assert data["hardware_profile"]
    # git_* and openzfs_version may be None depending on environment, but the
    # keys must always be present and packages is always a dict.
    for key in ("git_commit", "git_branch", "openzfs_version"):
        assert key in data
    assert isinstance(data["packages"], dict)


def test_list_media_empty(client: TestClient) -> None:
    r = client.get("/media")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_upload_and_retrieve(client: TestClient, tmp_path: Path) -> None:
    content = b"fake image data"
    r = client.post(
        "/upload",
        files={"file": ("test.jpg", content, "image/jpeg")},
    )
    assert r.status_code == 200
    item = r.json()
    assert item["kind"] == "image"
    assert item["filename"] == "test.jpg"
    item_id = item["id"]

    # List should now show one item.
    r2 = client.get("/media")
    assert r2.json()["total"] == 1

    # Retrieve the file.
    r3 = client.get(f"/media/{item_id}")
    assert r3.status_code == 200
    assert r3.content == content


def test_media_thumbnail(client: TestClient) -> None:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (1200, 900), (120, 60, 30)).save(buf, "JPEG")
    r = client.post(
        "/upload", files={"file": ("photo.jpg", buf.getvalue(), "image/jpeg")}
    )
    item_id = r.json()["id"]

    t = client.get(f"/media/{item_id}/thumb")
    assert t.status_code == 200
    assert t.headers["content-type"] == "image/jpeg"
    thumb = Image.open(BytesIO(t.content))
    assert max(thumb.size) <= 400  # bounded to the requested size
    assert len(t.content) < 900 * 1200  # much smaller than the source


def test_patch_media(client: TestClient) -> None:
    # Upload first.
    r = client.post(
        "/upload",
        files={"file": ("photo.jpg", b"data", "image/jpeg")},
    )
    item_id = r.json()["id"]

    r2 = client.patch(f"/media/{item_id}", json={"do_not_display": True})
    assert r2.status_code == 200
    assert r2.json()["do_not_display"] is True

    # Patched item should not appear in /media list.
    r3 = client.get("/media")
    assert r3.json()["total"] == 0


def test_delete_media_trashes(client: TestClient) -> None:
    r = client.post(
        "/upload",
        files={"file": ("del.jpg", b"bytes", "image/jpeg")},
    )
    item_id = r.json()["id"]

    r2 = client.delete(f"/media/{item_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "trashed"

    r3 = client.get("/media")
    assert r3.json()["total"] == 0


def test_delete_nonexistent(client: TestClient) -> None:
    r = client.delete("/media/does-not-exist")
    assert r.status_code == 404


def test_get_nonexistent(client: TestClient) -> None:
    r = client.get("/media/does-not-exist")
    assert r.status_code == 404


def test_upload_page_redirects_to_dashboard(client: TestClient) -> None:
    r = client.get("/upload", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/dashboard"


def test_dashboard_page(client: TestClient) -> None:
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Dashboard" in r.text
    # Single source of truth: upload UI is folded into the dashboard page.
    assert "dropzone" in r.text
    assert "file-input" in r.text
    assert 'id="grid"' in r.text
    assert "control-hint" in r.text
    assert 'MALMBERG_ROLE = "server"' in r.text
    # Domain split: "play on the frame" selectors live in the display domain,
    # library search boxes + People review UI live in the library domain.
    assert 'id="frame-person-play-btn"' in r.text
    assert 'id="frame-place-play-btn"' in r.text
    assert 'id="people-toggle"' in r.text
    assert 'id="review-backdrop"' in r.text
    assert 'id="by-person"' in r.text


# ---------------------------------------------------------------------------
# Recycle bin (trash / restore)
# ---------------------------------------------------------------------------


def test_trash_list_and_restore_round_trip(client: TestClient) -> None:
    r = client.post("/upload", files={"file": ("bin.jpg", b"trashme", "image/jpeg")})
    item_id = r.json()["id"]

    d = client.delete(f"/media/{item_id}")
    assert d.status_code == 200
    assert d.json()["status"] == "trashed"

    # Excluded from the normal library view...
    assert client.get("/media").json()["total"] == 0
    # ...but present in the recycle bin.
    trash = client.get("/media/trash")
    assert trash.status_code == 200
    trash_data = trash.json()
    assert trash_data["total"] == 1
    assert trash_data["items"][0]["id"] == item_id

    # A trashed item's thumbnail/original are still fetchable (recycle bin
    # preview) from the trash location.
    orig = client.get(f"/media/{item_id}")
    assert orig.status_code == 200
    assert orig.content == b"trashme"

    restore = client.post(f"/media/{item_id}/restore")
    assert restore.status_code == 200
    assert restore.json()["trashed_at"] is None

    assert client.get("/media").json()["total"] == 1
    assert client.get("/media/trash").json()["total"] == 0


def test_restore_nonexistent(client: TestClient) -> None:
    r = client.post("/media/does-not-exist/restore")
    assert r.status_code == 404


def test_restore_not_trashed(client: TestClient) -> None:
    r = client.post("/upload", files={"file": ("keep.jpg", b"keepme", "image/jpeg")})
    item_id = r.json()["id"]
    r2 = client.post(f"/media/{item_id}/restore")
    assert r2.status_code == 500


# ---------------------------------------------------------------------------
# Self-restart
# ---------------------------------------------------------------------------


def test_admin_restart_triggers_execv(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ack 200 first, then re-exec via os.execv -- captured, never actually run."""
    from malmberg_server.api import routes as routes_module

    calls: list[list[str]] = []
    monkeypatch.setattr(
        routes_module.os, "execv", lambda path, argv: calls.append(argv)
    )

    class _ImmediateLoop:
        def call_later(self, delay: float, fn) -> None:
            fn()

    monkeypatch.setattr(
        routes_module.asyncio, "get_event_loop", lambda: _ImmediateLoop()
    )

    r = client.post("/admin/restart")
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"
    assert calls == [[sys.executable, "-m", "malmberg_server"]]


def test_control_restart_proxies_to_display(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from malmberg_server.api import routes as routes_module

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": "restarting"}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def request(
            self, method: str, url: str, json: object = None
        ) -> _FakeResponse:
            assert method == "POST"
            assert url.endswith("/admin/restart")
            return _FakeResponse()

    monkeypatch.setattr(routes_module.httpx, "AsyncClient", _FakeAsyncClient)

    cfg = ServerConfig(fs_root=tmp_path, display_url="http://display.local:8443")
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir()
    app_client = TestClient(routes_module.build_app(cfg))

    r = app_client.post("/control/restart")
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"


def test_stats_empty(client: TestClient) -> None:
    r = client.get("/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["images"] == 0
    assert data["videos"] == 0
    assert data["undated"] == 0
    assert data["earliest"] is None
    assert data["latest"] is None
    assert data["by_year"] == {}


def test_stats_after_upload(client: TestClient) -> None:
    client.post("/upload", files={"file": ("a.jpg", b"aaa", "image/jpeg")})
    client.post("/upload", files={"file": ("b.jpg", b"bbb", "image/jpeg")})
    r = client.get("/stats")
    data = r.json()
    assert data["total"] == 2
    assert data["images"] == 2
    assert data["videos"] == 0


def test_media_search_by_place(client: TestClient, tmp_path: Path) -> None:
    from malmberg_core.models import MediaItem, MediaMetadata
    from malmberg_server.api.routes import build_app
    from malmberg_server.ingest.store import MediaStore

    store = MediaStore()
    store.add(
        MediaItem(
            kind="image",
            filename="beach.jpg",
            server_path="2024/01/01/beach.jpg",
            meta=MediaMetadata(sha256="h1", place="Tampa, Florida, US"),
        )
    )
    store.add(
        MediaItem(
            kind="image",
            filename="mountain.jpg",
            server_path="2024/01/01/mountain.jpg",
            meta=MediaMetadata(sha256="h2", place="Denver, Colorado, US"),
        )
    )
    cfg = ServerConfig(fs_root=tmp_path)
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir(exist_ok=True)
    c = TestClient(build_app(cfg, store=store))

    r = c.get("/media", params={"q": "tampa"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["filename"] == "beach.jpg"

    r_stats = c.get("/stats")
    assert r_stats.json()["by_place"] == {
        "Tampa, Florida, US": 1,
        "Denver, Colorado, US": 1,
    }


def test_places_autocomplete(client: TestClient, tmp_path: Path) -> None:
    from malmberg_core.models import MediaItem, MediaMetadata
    from malmberg_server.api.routes import build_app
    from malmberg_server.ingest.store import MediaStore

    store = MediaStore()
    store.add(
        MediaItem(
            kind="image",
            filename="beach.jpg",
            server_path="2024/01/01/beach.jpg",
            meta=MediaMetadata(sha256="h1", place="Tampa, Florida, US"),
        )
    )
    store.add(
        MediaItem(
            kind="image",
            filename="mountain.jpg",
            server_path="2024/01/01/mountain.jpg",
            meta=MediaMetadata(sha256="h2", place="Orlando, Florida, US"),
        )
    )
    cfg = ServerConfig(fs_root=tmp_path)
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir(exist_ok=True)
    c = TestClient(build_app(cfg, store=store))

    r = c.get("/places", params={"q": "tam"})
    assert r.status_code == 200
    assert r.json() == ["Tampa, Florida, US"]

    r_all = c.get("/places", params={"q": "florida"})
    assert set(r_all.json()) == {"Tampa, Florida, US", "Orlando, Florida, US"}


def test_media_search_by_filename(client: TestClient) -> None:
    client.post("/upload", files={"file": ("beach.jpg", b"aaa", "image/jpeg")})
    client.post("/upload", files={"file": ("mountain.jpg", b"bbb", "image/jpeg")})
    r = client.get("/media", params={"q": "beach"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["filename"] == "beach.jpg"

    r_ci = client.get("/media", params={"q": "BEACH"})
    assert r_ci.json()["total"] == 1


def test_media_search_no_match(client: TestClient) -> None:
    client.post("/upload", files={"file": ("beach.jpg", b"aaa", "image/jpeg")})
    r = client.get("/media", params={"q": "zzz-no-match"})
    assert r.json()["total"] == 0
    assert r.json()["items"] == []


def test_media_search_with_pagination(client: TestClient) -> None:
    for i in range(5):
        client.post(
            "/upload",
            files={"file": (f"photo-{i}.jpg", f"data{i}".encode(), "image/jpeg")},
        )
    r = client.get("/media", params={"q": "photo", "page": 1, "page_size": 2})
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["has_next"] is True

    r2 = client.get("/media", params={"q": "photo", "page": 3, "page_size": 2})
    data2 = r2.json()
    assert len(data2["items"]) == 1
    assert data2["has_next"] is False


def test_list_media_sort_recent(client: TestClient) -> None:
    client.post("/upload", files={"file": ("a.jpg", b"aaa", "image/jpeg")})
    client.post("/upload", files={"file": ("b.jpg", b"bbb", "image/jpeg")})
    r = client.get("/media", params={"sort": "recent"})
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_control_endpoints_503_without_display_url(client: TestClient) -> None:
    for path in ("/control/next", "/control/prev", "/control/pause"):
        r = client.post(path)
        assert r.status_code == 503
    r = client.get("/control/status")
    assert r.status_code == 503


def test_control_play_all_503_without_display_url(client: TestClient) -> None:
    r = client.post("/control/play-all")
    assert r.status_code == 503


def test_control_show_503_without_display_url(client: TestClient) -> None:
    r = client.post("/control/show/some-id")
    assert r.status_code == 503


def test_control_playlist_without_display_url(client: TestClient) -> None:
    # Unknown playlist should 404 before ever consulting display_url.
    r = client.post("/control/playlist/does-not-exist")
    assert r.status_code == 404

    client.post("/playlists", json={"name": "trip"})
    r = client.post("/control/playlist/trip")
    assert r.status_code == 503


def test_control_status_proxies_to_display(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from malmberg_server.api import routes as routes_module

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"paused": False, "queue_depth": 3}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def request(
            self, method: str, url: str, json: object = None
        ) -> _FakeResponse:
            assert method == "GET"
            assert url.endswith("/status")
            return _FakeResponse()

    monkeypatch.setattr(routes_module.httpx, "AsyncClient", _FakeAsyncClient)

    cfg = ServerConfig(fs_root=tmp_path, display_url="http://10.0.0.5:8443")
    for d in ("media", "uploads", "cloud", ".trash", "logs"):
        (tmp_path / d).mkdir()
    app_client = TestClient(routes_module.build_app(cfg))

    r = app_client.get("/control/status")
    assert r.status_code == 200
    body = r.json()
    # Proxied display status is merged with the multi-display roster.
    assert body["paused"] is False
    assert body["queue_depth"] == 3
    assert body["selected"] == "display"
    assert body["displays"] == [{"name": "display"}]


def test_server_config_defaults() -> None:
    cfg = ServerConfig()
    assert cfg.hide_policy == "delete"
    assert cfg.trash_purge_days == 30
    assert cfg.max_upload_mb == 500


def test_server_config_validation() -> None:
    with pytest.raises(Exception):
        ServerConfig(max_upload_mb=0)


def test_server_config_display_url_default_none() -> None:
    assert ServerConfig().display_url is None


def test_server_config_display_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MALMBERG_DISPLAY_URL", "http://10.0.0.5:8443")
    assert ServerConfig._env_overrides()["display_url"] == "http://10.0.0.5:8443"


# ----------------------------------------------------------------------
# Permanent delete
# ----------------------------------------------------------------------


def test_permanent_delete_removes_file_and_index_entry(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.post("/upload", files={"file": ("perm.jpg", b"perm data", "image/jpeg")})
    item = r.json()
    item_id = item["id"]
    media_path = tmp_path / "media" / item["server_path"]
    assert media_path.is_file()

    r2 = client.delete(f"/media/{item_id}", params={"permanent": "true"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "deleted"
    assert not media_path.is_file()

    r3 = client.get(f"/media/{item_id}")
    assert r3.status_code == 404

    # Should not have landed in trash.
    trash_files = list((tmp_path / ".trash").rglob("*"))
    assert all(not f.is_file() for f in trash_files)


def test_permanent_delete_missing_item_404s(client: TestClient) -> None:
    r = client.delete("/media/does-not-exist", params={"permanent": "true"})
    assert r.status_code == 404


def test_soft_delete_still_recoverable_in_trash(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.post("/upload", files={"file": ("soft.jpg", b"soft data", "image/jpeg")})
    item_id = r.json()["id"]
    r2 = client.delete(f"/media/{item_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "trashed"
    trash_files = [f for f in (tmp_path / ".trash").rglob("*") if f.is_file()]
    assert len(trash_files) == 1


def test_media_info_returns_full_item(client: TestClient) -> None:
    r = client.post("/upload", files={"file": ("info.jpg", b"info data", "image/jpeg")})
    item_id = r.json()["id"]
    r2 = client.get(f"/media/{item_id}/info")
    assert r2.status_code == 200
    data = r2.json()
    assert data["id"] == item_id
    assert data["filename"] == "info.jpg"
    assert "meta" in data


def test_media_info_missing_404s(client: TestClient) -> None:
    r = client.get("/media/does-not-exist/info")
    assert r.status_code == 404


# ----------------------------------------------------------------------
# Bulk delete
# ----------------------------------------------------------------------


def test_bulk_delete_soft(client: TestClient, tmp_path: Path) -> None:
    ids = []
    for name in ("a.jpg", "b.jpg"):
        r = client.post("/upload", files={"file": (name, name.encode(), "image/jpeg")})
        ids.append(r.json()["id"])

    r = client.post("/media/bulk-delete", json={"ids": ids, "permanent": False})
    assert r.status_code == 200
    data = r.json()
    assert sorted(data["deleted"]) == sorted(ids)
    assert data["failed"] == []

    trash_files = [f for f in (tmp_path / ".trash").rglob("*") if f.is_file()]
    assert len(trash_files) == 2


def test_bulk_delete_permanent_and_unknown_ids(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.post("/upload", files={"file": ("c.jpg", b"ccc", "image/jpeg")})
    item_id = r.json()["id"]

    r2 = client.post(
        "/media/bulk-delete",
        json={"ids": [item_id, "unknown-id"], "permanent": True},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert data["deleted"] == [item_id]
    assert data["failed"] == ["unknown-id"]

    trash_files = [f for f in (tmp_path / ".trash").rglob("*") if f.is_file()]
    assert trash_files == []


# ----------------------------------------------------------------------
# Playlists (programmed slideshows)
# ----------------------------------------------------------------------


def test_playlist_crud_lifecycle(client: TestClient, tmp_path: Path) -> None:
    r = client.get("/playlists")
    assert r.status_code == 200
    assert r.json() == []

    r = client.post("/playlists", json={"name": "vacation"})
    assert r.status_code == 200
    assert r.json() == {"name": "vacation", "count": 0}

    # Duplicate name is rejected.
    r = client.post("/playlists", json={"name": "vacation"})
    assert r.status_code == 409

    r = client.get("/playlists")
    assert r.json() == [{"name": "vacation", "count": 0}]

    up = client.post("/upload", files={"file": ("v.jpg", b"vvv", "image/jpeg")})
    item_id = up.json()["id"]

    r = client.post("/playlists/vacation/items", json={"item_id": item_id})
    assert r.status_code == 200
    assert r.json() == {"name": "vacation", "count": 1}

    # Adding the same item again is a no-op (no duplicates).
    r = client.post("/playlists/vacation/items", json={"item_id": item_id})
    assert r.json()["count"] == 1

    r = client.delete(f"/playlists/vacation/items/{item_id}")
    assert r.status_code == 200
    assert r.json()["count"] == 0

    r = client.delete("/playlists/vacation")
    assert r.status_code == 200
    r = client.get("/playlists")
    assert r.json() == []

    r = client.delete("/playlists/vacation")
    assert r.status_code == 404


def test_playlist_items_bulk_add(client: TestClient) -> None:
    client.post("/playlists", json={"name": "family"})
    ids = []
    for name in ("x.jpg", "y.jpg"):
        r = client.post("/upload", files={"file": (name, name.encode(), "image/jpeg")})
        ids.append(r.json()["id"])

    r = client.post("/playlists/family/items/bulk", json={"ids": ids})
    assert r.status_code == 200
    assert r.json() == {"name": "family", "count": 2}


def test_playlist_add_item_missing_playlist_404s(client: TestClient) -> None:
    r = client.post("/playlists/nope/items", json={"item_id": "some-id"})
    assert r.status_code == 404


def test_playlists_persist_to_disk(client: TestClient, tmp_path: Path) -> None:
    client.post("/playlists", json={"name": "persisted"})
    playlists_path = tmp_path / "logs" / "playlists.json"
    assert playlists_path.is_file()
    assert "persisted" in playlists_path.read_text()
