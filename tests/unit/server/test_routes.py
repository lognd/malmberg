"""Tests for malmberg_server.api.routes."""

from __future__ import annotations

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


def test_upload_page(client: TestClient) -> None:
    r = client.get("/upload")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Bulk Upload" in r.text


def test_dashboard_page(client: TestClient) -> None:
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Dashboard" in r.text


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

        async def request(self, method: str, url: str) -> _FakeResponse:
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
    assert r.json() == {"paused": False, "queue_depth": 3}


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
