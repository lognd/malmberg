"""Tests for malmberg_server.ingest."""

from __future__ import annotations

from pathlib import Path

import pytest

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import extract_exif, sha256_of_file
from malmberg_server.ingest.store import MediaStore

# ---------------------------------------------------------------------------
# sha256_of_file
# ---------------------------------------------------------------------------


def test_sha256_of_file(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    digest = sha256_of_file(f)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_sha256_of_file_missing(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        sha256_of_file(tmp_path / "nope.bin")


# ---------------------------------------------------------------------------
# extract_exif
# ---------------------------------------------------------------------------


def test_extract_exif_video(tmp_path: Path) -> None:
    """Video files return minimal metadata without EXIF parsing."""
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00" * 16)
    result = extract_exif(f)
    assert result.is_ok
    meta = result.danger_ok
    assert meta.sha256 != ""
    assert meta.taken_at is None


def test_extract_exif_non_image(tmp_path: Path) -> None:
    """Non-image, non-video files return ExifError."""
    f = tmp_path / "text.jpg"
    f.write_bytes(b"not an image at all")
    result = extract_exif(f)
    assert result.is_err
    assert result.danger_err is IngestError.ExifError


def test_extract_exif_missing_file(tmp_path: Path) -> None:
    result = extract_exif(tmp_path / "ghost.jpg")
    assert result.is_err
    assert result.danger_err is IngestError.IOError


def test_extract_exif_plain_png(tmp_path: Path) -> None:
    """A valid PNG with no EXIF still returns Ok with width/height."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    img = Image.new("RGB", (10, 20), color=(255, 0, 0))
    path = tmp_path / "red.png"
    img.save(path)
    result = extract_exif(path)
    assert result.is_ok
    meta = result.danger_ok
    assert meta.width == 10
    assert meta.height == 20
    assert meta.sha256 != ""


# ---------------------------------------------------------------------------
# MediaStore
# ---------------------------------------------------------------------------


def _make_item(**kwargs) -> MediaItem:
    defaults = dict(
        kind="image",
        filename="photo.jpg",
        server_path="2024/01/01/photo.jpg",
    )
    defaults.update(kwargs)
    return MediaItem(**defaults)


def test_store_add_and_get() -> None:
    s = MediaStore()
    item = _make_item()
    s.add(item)
    assert s.get(item.id) is item
    assert len(s) == 1


def test_store_list_pagination() -> None:
    s = MediaStore()
    for i in range(10):
        s.add(_make_item(filename=f"{i}.jpg", server_path=f"2024/01/01/{i}.jpg"))
    page = s.list(page=1, page_size=3)
    assert len(page.items) == 3
    assert page.total == 10
    assert page.has_next


def test_store_list_skips_hidden() -> None:
    s = MediaStore()
    item = _make_item()
    s.add(item)
    s.patch(item.id, {"do_not_display": True})
    page = s.list(skip_hidden=True)
    assert page.total == 0


def test_store_patch_not_found() -> None:
    s = MediaStore()
    result = s.patch("nonexistent", {"do_not_display": True})
    assert result.is_err
    assert result.danger_err is IngestError.NotFound


def test_store_delete_trash(tmp_path: Path) -> None:
    s = MediaStore()
    media_root = tmp_path / "media"
    trash_root = tmp_path / ".trash"
    rel = "2024/01/01/photo.jpg"
    (media_root / "2024/01/01").mkdir(parents=True)
    (media_root / rel).write_bytes(b"img")

    item = _make_item(server_path=rel, hide_policy="delete")
    s.add(item)

    result = s.delete(item.id, trash_root, media_root)
    assert result.is_ok
    assert result.danger_ok["status"] == "trashed"
    assert s.get(item.id) is None
    assert (trash_root / rel).is_file()


def test_store_delete_keep(tmp_path: Path) -> None:
    s = MediaStore()
    item = _make_item(hide_policy="keep")
    s.add(item)
    result = s.delete(item.id, tmp_path / ".trash", tmp_path / "media")
    assert result.is_ok
    assert result.danger_ok["status"] == "hidden"
    kept = s.get(item.id)
    assert kept is not None
    assert kept.do_not_display


def test_store_delete_not_found() -> None:
    s = MediaStore()
    result = s.delete("ghost", Path("/trash"), Path("/media"))
    assert result.is_err
    assert result.danger_err is IngestError.NotFound


def test_store_persistence(tmp_path: Path) -> None:
    s = MediaStore()
    item = _make_item(meta=MediaMetadata(sha256="abc123"))
    s.add(item)
    idx = tmp_path / "index.jsonl"
    save_result = s.save_to_disk(idx)
    assert save_result.is_ok

    s2 = MediaStore()
    load_result = s2.load_from_disk(idx)
    assert load_result.is_ok
    assert load_result.danger_ok == 1
    loaded = s2.get(item.id)
    assert loaded is not None
    assert loaded.meta.sha256 == "abc123"


def test_store_sha256_exists() -> None:
    s = MediaStore()
    item = _make_item(meta=MediaMetadata(sha256="deadbeef"))
    s.add(item)
    assert s.sha256_exists("deadbeef")
    assert not s.sha256_exists("cafebabe")
