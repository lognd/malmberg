"""System tests: full server-to-display upload-and-fetch pipeline via ASGI."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from malmberg_display.slideshow.producers.server import ServerProducer
from malmberg_server.api.routes import build_app as build_server_app
from malmberg_server.app.config import ServerConfig
from malmberg_server.ingest.store import MediaStore
from tests.conftest import asgi_client


def _make_png(r: int = 100, g: int = 150, b: int = 200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (r, g, b)).save(buf, "PNG")
    return buf.getvalue()


def _setup_server(tmp_path: Path) -> tuple[ServerConfig, MediaStore]:
    cfg = ServerConfig(fs_root=tmp_path / "server")
    for sub in ("media", "uploads", "cloud", ".trash", "logs"):
        (cfg.fs_root / sub).mkdir(parents=True)
    return cfg, MediaStore()


# ---------------------------------------------------------------------------
# Upload then fetch via ServerProducer (ASGI transport -- no real network)
# ---------------------------------------------------------------------------


async def test_upload_and_producer_fetch(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    server_app = build_server_app(cfg, store)

    async with asgi_client(server_app, "http://server") as sc:
        r = await sc.post(
            "/upload", files={"file": ("red.png", _make_png(), "image/png")}
        )
        assert r.status_code == 200
        item_id = r.json()["id"]

    cache = tmp_path / "cache"
    async with asgi_client(server_app, "http://server") as sc:
        producer = ServerProducer("http://server", cache, sc)
        items = [item async for item in producer.items()]

    assert len(items) == 1
    assert items[0].item_id == item_id
    assert (cache / item_id / "red.png").is_file()


async def test_multiple_uploads_all_fetched(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    server_app = build_server_app(cfg, store)

    async with asgi_client(server_app, "http://server") as sc:
        ids = []
        for i in range(3):
            r = await sc.post(
                "/upload",
                files={
                    "file": (f"img{i}.png", _make_png(i * 50, 100, 200), "image/png")
                },
            )
            assert r.status_code == 200
            ids.append(r.json()["id"])

    cache = tmp_path / "cache"
    async with asgi_client(server_app, "http://server") as sc:
        producer = ServerProducer("http://server", cache, sc)
        items = [item async for item in producer.items()]

    assert len(items) == 3
    fetched_ids = {i.item_id for i in items}
    assert fetched_ids == set(ids)


async def test_producer_cache_hit_skips_download(tmp_path: Path) -> None:
    """If the file is already in cache, ServerProducer must not re-download."""
    cfg, store = _setup_server(tmp_path)
    server_app = build_server_app(cfg, store)

    async with asgi_client(server_app, "http://server") as sc:
        r = await sc.post(
            "/upload", files={"file": ("photo.png", _make_png(), "image/png")}
        )
        item_id = r.json()["id"]

    cache = tmp_path / "cache"
    (cache / item_id).mkdir(parents=True)
    cached_file = cache / item_id / "photo.png"
    cached_file.write_bytes(b"already cached")

    download_count = 0
    original_download = ServerProducer._download

    async def counting_download(self, iid, filename, dest):  # type: ignore[override]
        nonlocal download_count
        download_count += 1
        return await original_download(self, iid, filename, dest)

    ServerProducer._download = counting_download  # type: ignore[method-assign]
    try:
        async with asgi_client(server_app, "http://server") as sc:
            producer = ServerProducer("http://server", cache, sc)
            items = [item async for item in producer.items()]
    finally:
        ServerProducer._download = original_download  # type: ignore[method-assign]

    assert len(items) == 1
    assert download_count == 0
    assert cached_file.read_bytes() == b"already cached"


async def test_producer_pagination(tmp_path: Path) -> None:
    """ServerProducer retrieves all items across multiple pages."""
    cfg, store = _setup_server(tmp_path)
    server_app = build_server_app(cfg, store)

    async with asgi_client(server_app, "http://server") as sc:
        for i in range(6):
            png = _make_png(i * 20 + 10, 100, 200)
            await sc.post("/upload", files={"file": (f"p{i}.png", png, "image/png")})

    cache = tmp_path / "cache"
    async with asgi_client(server_app, "http://server") as sc:
        producer = ServerProducer("http://server", cache, sc)
        items = [item async for item in producer.items()]

    assert len(items) == 6


# ---------------------------------------------------------------------------
# Delete from server, then re-fetch: deleted item must not appear
# ---------------------------------------------------------------------------


async def test_deleted_item_not_fetched(tmp_path: Path) -> None:
    cfg, store = _setup_server(tmp_path)
    server_app = build_server_app(cfg, store)

    async with asgi_client(server_app, "http://server") as sc:
        r1 = await sc.post(
            "/upload", files={"file": ("a.png", _make_png(10, 20, 30), "image/png")}
        )
        r2 = await sc.post(
            "/upload", files={"file": ("b.png", _make_png(40, 50, 60), "image/png")}
        )
        id1 = r1.json()["id"]
        await sc.delete(f"/media/{id1}")

    cache = tmp_path / "cache"
    async with asgi_client(server_app, "http://server") as sc:
        producer = ServerProducer("http://server", cache, sc)
        items = [item async for item in producer.items()]

    assert len(items) == 1
    assert items[0].item_id == r2.json()["id"]
