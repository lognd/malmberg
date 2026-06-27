"""Integration tests: server FastAPI app with real filesystem I/O."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from malmberg_server.api.routes import build_app
from malmberg_server.app.config import ServerConfig
from malmberg_server.ingest.store import MediaStore
from tests.conftest import asgi_client


def _make_png(w: int = 20, h: int = 20) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


def _setup_server(tmp_path: Path) -> tuple[ServerConfig, MediaStore]:
    cfg = ServerConfig(fs_root=tmp_path / "server")
    for sub in ("media", "uploads", "cloud", ".trash", "logs"):
        (cfg.fs_root / sub).mkdir(parents=True)
    return cfg, MediaStore()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


async def test_root(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "server"
    assert "version" in data
    assert "mac" in data


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


async def test_status(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert data["uptime_s"] >= 0
    assert "disk_used_bytes" in data
    assert "disk_total_bytes" in data
    assert data["version"] != ""


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------


async def test_upload_png(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    png = _make_png()
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.post("/upload", files={"file": ("photo.png", png, "image/png")})
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["filename"] == "photo.png"
    assert data["kind"] == "image"


async def test_upload_duplicate(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    png = _make_png()
    async with asgi_client(build_app(cfg, store)) as c:
        r1 = await c.post("/upload", files={"file": ("photo.png", png, "image/png")})
        assert r1.status_code == 200
        r2 = await c.post("/upload", files={"file": ("photo.png", png, "image/png")})
        assert r2.status_code == 409


async def test_upload_no_filename(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.post(
            "/upload", files={"file": ("", b"data", "application/octet-stream")}
        )
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# GET /media  (listing)
# ---------------------------------------------------------------------------


async def test_list_media_empty(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.get("/media")
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_list_media_after_upload(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    png = _make_png()
    async with asgi_client(build_app(cfg, store)) as c:
        await c.post("/upload", files={"file": ("img.png", png, "image/png")})
        r = await c.get("/media")
    assert r.status_code == 200
    assert r.json()["total"] == 1


async def test_list_media_pagination(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        for i in range(5):
            png = _make_png(w=i + 5, h=i + 5)
            await c.post("/upload", files={"file": (f"img{i}.png", png, "image/png")})
        r = await c.get("/media", params={"page": 1, "page_size": 3})
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 3
    assert data["total"] == 5
    assert data["has_next"] is True


# ---------------------------------------------------------------------------
# GET /media/{id}
# ---------------------------------------------------------------------------


async def test_get_media_file(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    png = _make_png()
    async with asgi_client(build_app(cfg, store)) as c:
        up = await c.post("/upload", files={"file": ("img.png", png, "image/png")})
        item_id = up.json()["id"]
        r = await c.get(f"/media/{item_id}")
    assert r.status_code == 200


async def test_get_media_not_found(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.get("/media/nonexistent-id")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /media/{id}
# ---------------------------------------------------------------------------


async def test_patch_hide(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    png = _make_png()
    async with asgi_client(build_app(cfg, store)) as c:
        up = await c.post("/upload", files={"file": ("img.png", png, "image/png")})
        item_id = up.json()["id"]
        r = await c.patch(f"/media/{item_id}", json={"do_not_display": True})
        assert r.status_code == 200
        assert r.json()["do_not_display"] is True
        listing = await c.get("/media")
        assert listing.json()["total"] == 0


async def test_patch_not_found(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.patch("/media/ghost", json={"do_not_display": True})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /media/{id}
# ---------------------------------------------------------------------------


async def test_delete_trashes_file(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    png = _make_png()
    async with asgi_client(build_app(cfg, store)) as c:
        up = await c.post("/upload", files={"file": ("img.png", png, "image/png")})
        item_id = up.json()["id"]
        r = await c.delete(f"/media/{item_id}")
        assert r.status_code == 200
        assert r.json()["status"] in ("trashed", "hidden")
        listing = await c.get("/media")
        assert listing.json()["total"] == 0


async def test_delete_not_found(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    async with asgi_client(build_app(cfg, store)) as c:
        r = await c.delete("/media/ghost")
    assert r.status_code == 404
