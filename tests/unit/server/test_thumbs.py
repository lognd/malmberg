"""Tests for malmberg_server.ingest.thumbs (the background thumbnail warmer)."""

from __future__ import annotations

from pathlib import Path

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.ingest.store import MediaStore
from malmberg_server.ingest.thumbs import (
    WARM_SIZES,
    _warm_one,
    missing_thumbs,
    thumb_path,
)


def _make_item(item_id: str, **kwargs) -> MediaItem:
    defaults = dict(
        id=item_id,
        kind="image",
        filename=f"{item_id}.jpg",
        server_path=f"p/{item_id}.jpg",
        meta=MediaMetadata(sha256=item_id),
    )
    defaults.update(kwargs)
    return MediaItem(**defaults)


def test_missing_thumbs_lists_every_size_then_none(tmp_path: Path) -> None:
    store = MediaStore()
    store.add(_make_item("i1"))
    fs_root = tmp_path / "fs"

    pending = missing_thumbs(store, fs_root)
    assert sorted(size for _, size in pending) == sorted(WARM_SIZES)

    # An existing thumbnail is skipped -- the on-disk file IS the state.
    for size in WARM_SIZES:
        dest = thumb_path(fs_root, "i1", size)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpg")
    assert missing_thumbs(store, fs_root) == []


def test_missing_thumbs_skips_trashed(tmp_path: Path) -> None:
    """Warming a trashed item would re-fill the cache for a deleted photo."""
    from datetime import datetime, timezone

    store = MediaStore()
    store.add(_make_item("i1", trashed_at=datetime.now(timezone.utc)))
    assert missing_thumbs(store, tmp_path) == []


def test_warm_one_writes_a_real_thumbnail(tmp_path: Path) -> None:
    from PIL import Image

    fs_root = tmp_path / "fs"
    media_root = tmp_path / "media"
    (media_root / "p").mkdir(parents=True)
    Image.new("RGB", (900, 600), (200, 30, 30)).save(media_root / "p" / "i1.jpg")

    store = MediaStore()
    store.add(_make_item("i1"))

    assert _warm_one(store, fs_root, media_root, "i1", 200) is True
    dest = thumb_path(fs_root, "i1", 200)
    assert dest.is_file()
    with Image.open(dest) as img:
        assert max(img.size) <= 200
    assert missing_thumbs(store, fs_root) == [("i1", 400)]


def test_warm_one_missing_file_is_not_fatal(tmp_path: Path) -> None:
    """A row whose file is gone is skipped, not raised -- one bad item must
    never stall the warm-up for the whole library."""
    store = MediaStore()
    store.add(_make_item("i1"))
    assert _warm_one(store, tmp_path / "fs", tmp_path / "media", "i1", 200) is False
    assert _warm_one(store, tmp_path / "fs", tmp_path / "media", "nope", 200) is False
