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


def test_server_config_defaults() -> None:
    cfg = ServerConfig()
    assert cfg.hide_policy == "delete"
    assert cfg.trash_purge_days == 30
    assert cfg.max_upload_mb == 500


def test_server_config_validation() -> None:
    with pytest.raises(Exception):
        ServerConfig(max_upload_mb=0)
