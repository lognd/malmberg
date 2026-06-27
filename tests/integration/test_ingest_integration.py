"""Integration tests: ingest pipeline with real file I/O (no HTTP layer)."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image
from starlette.datastructures import UploadFile

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import extract_exif, sha256_of_file
from malmberg_server.ingest.store import MediaStore
from malmberg_server.ingest.upload import handle_upload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _png_bytes(w: int = 30, h: int = 30) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _make_upload(content: bytes, filename: str) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


# ---------------------------------------------------------------------------
# sha256_of_file
# ---------------------------------------------------------------------------


def test_sha256_reproducible(tmp_path: Path) -> None:
    data = b"hello integration"
    f = tmp_path / "data.bin"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_of_file(f) == expected


def test_sha256_large_file(tmp_path: Path) -> None:
    data = b"x" * (1024 * 1024)  # 1 MiB
    f = tmp_path / "big.bin"
    f.write_bytes(data)
    digest = sha256_of_file(f)
    assert len(digest) == 64


# ---------------------------------------------------------------------------
# extract_exif
# ---------------------------------------------------------------------------


def test_extract_exif_png_dimensions(tmp_path: Path) -> None:
    img_path = tmp_path / "img.png"
    img_path.write_bytes(_png_bytes(40, 80))
    result = extract_exif(img_path)
    assert result.is_ok
    meta = result.danger_ok
    assert meta.width == 40
    assert meta.height == 80
    assert len(meta.sha256) == 64


def test_extract_exif_video_stub(tmp_path: Path) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00" * 64)
    result = extract_exif(f)
    assert result.is_ok
    meta = result.danger_ok
    assert meta.sha256 != ""
    assert meta.taken_at is None
    assert meta.width is None


def test_extract_exif_corrupt_image(tmp_path: Path) -> None:
    f = tmp_path / "bad.jpg"
    f.write_bytes(b"not an image")
    result = extract_exif(f)
    assert result.is_err
    assert result.danger_err is IngestError.ExifError


def test_extract_exif_missing(tmp_path: Path) -> None:
    result = extract_exif(tmp_path / "ghost.png")
    assert result.is_err
    assert result.danger_err is IngestError.IOError


# ---------------------------------------------------------------------------
# handle_upload -- end-to-end pipeline
# ---------------------------------------------------------------------------


async def test_handle_upload_png(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    upload_root = tmp_path / "uploads"
    media_root.mkdir()
    upload_root.mkdir()
    store = MediaStore()

    png = _png_bytes()
    upload = _make_upload(png, "shot.png")

    result = await handle_upload(
        file=upload,
        store=store,
        media_root=media_root,
        upload_root=upload_root,
        max_bytes=10 * 1024 * 1024,
    )
    assert result.is_ok
    item = result.danger_ok
    assert item.filename == "shot.png"
    assert item.kind == "image"
    # File moved to media/YYYY/MM/DD/
    dest = media_root / item.server_path
    assert dest.is_file()
    assert len(store) == 1


async def test_handle_upload_duplicate(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    upload_root = tmp_path / "uploads"
    media_root.mkdir()
    upload_root.mkdir()
    store = MediaStore()

    png = _png_bytes()
    for _ in range(2):
        upload = _make_upload(png, "dup.png")
        result = await handle_upload(
            file=upload,
            store=store,
            media_root=media_root,
            upload_root=upload_root,
            max_bytes=10 * 1024 * 1024,
        )

    assert result.is_err
    assert result.danger_err is IngestError.DuplicateFile


async def test_handle_upload_too_large(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    upload_root = tmp_path / "uploads"
    media_root.mkdir()
    upload_root.mkdir()
    store = MediaStore()

    large = b"x" * 1024
    upload = _make_upload(large, "big.png")
    result = await handle_upload(
        file=upload,
        store=store,
        media_root=media_root,
        upload_root=upload_root,
        max_bytes=100,
    )
    assert result.is_err
    assert result.danger_err is IngestError.FileTooLarge


async def test_handle_upload_video_stub(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    upload_root = tmp_path / "uploads"
    media_root.mkdir()
    upload_root.mkdir()
    store = MediaStore()

    upload = _make_upload(b"\x00" * 64, "video.mp4")
    result = await handle_upload(
        file=upload,
        store=store,
        media_root=media_root,
        upload_root=upload_root,
        max_bytes=10 * 1024 * 1024,
    )
    assert result.is_ok
    assert result.danger_ok.kind == "video"


# ---------------------------------------------------------------------------
# MediaStore persistence round-trip
# ---------------------------------------------------------------------------


def test_store_persistence_roundtrip(tmp_path: Path) -> None:
    store = MediaStore()
    item = MediaItem(
        kind="image",
        filename="photo.jpg",
        server_path="2024/01/01/photo.jpg",
        meta=MediaMetadata(sha256="cafebabe", width=100, height=200),
    )
    store.add(item)

    idx = tmp_path / "index.jsonl"
    assert store.save_to_disk(idx).is_ok

    store2 = MediaStore()
    load_res = store2.load_from_disk(idx)
    assert load_res.is_ok
    assert load_res.danger_ok == 1

    loaded = store2.get(item.id)
    assert loaded is not None
    assert loaded.meta.sha256 == "cafebabe"
    assert loaded.meta.width == 100
    assert loaded.filename == "photo.jpg"


def test_store_persistence_multiple_items(tmp_path: Path) -> None:
    store = MediaStore()
    for i in range(20):
        store.add(
            MediaItem(
                kind="image",
                filename=f"img{i}.jpg",
                server_path=f"2024/01/{i:02d}/img.jpg",
                meta=MediaMetadata(sha256=f"hash{i}"),
            )
        )
    idx = tmp_path / "index.jsonl"
    assert store.save_to_disk(idx).is_ok

    store2 = MediaStore()
    assert store2.load_from_disk(idx).danger_ok == 20
    page = store2.list(page=1, page_size=5)
    assert page.total == 20
    assert len(page.items) == 5
