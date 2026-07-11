"""Tests for malmberg_server.ingest."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import (
    META_SCHEMA_VERSION,
    extract_exif,
    make_thumbnail,
    sha256_of_file,
)
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
    # Trashed items stay in the index (recoverable via restore()) but are
    # excluded from normal list()/stats() views.
    trashed = s.get(item.id)
    assert trashed is not None
    assert trashed.trashed_at is not None
    assert trashed.trash_path == rel
    assert (trash_root / rel).is_file()
    assert s.list(skip_hidden=False).total == 0
    assert s.list_trash().total == 1

    restore_result = s.restore(item.id, trash_root, media_root)
    assert restore_result.is_ok
    restored = restore_result.danger_ok
    assert restored.trashed_at is None
    assert restored.trash_path is None
    assert (media_root / rel).is_file()
    assert not (trash_root / rel).is_file()
    assert s.list(skip_hidden=False).total == 1
    assert s.list_trash().total == 0


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


# ---------------------------------------------------------------------------
# Lazy metadata refresh (schema_version)
# ---------------------------------------------------------------------------


def test_store_get_refreshes_stale_metadata(tmp_path: Path) -> None:
    """An item with an old meta.schema_version self-heals on GET by id."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    media_root = tmp_path / "media"
    rel = "2024/01/01/photo.png"
    (media_root / "2024/01/01").mkdir(parents=True)
    img = Image.new("RGB", (33, 44), color=(0, 128, 255))
    img.save(media_root / rel)

    s = MediaStore()
    item = _make_item(
        server_path=rel,
        do_not_display=True,
        tags=["keepme"],
        dwell_override_s=12.0,
        meta=MediaMetadata(sha256="stale", schema_version=0, width=1, height=1),
    )
    s.add(item)

    refreshed = s.get(item.id, media_root=media_root)
    assert refreshed is not None
    assert refreshed.meta.schema_version == META_SCHEMA_VERSION
    assert refreshed.meta.width == 33
    assert refreshed.meta.height == 44
    # User-set fields survive the refresh.
    assert refreshed.do_not_display is True
    assert refreshed.tags == ["keepme"]
    assert refreshed.dwell_override_s == 12.0
    assert refreshed.meta.ingest_at == item.meta.ingest_at
    assert s.pop_dirty() is True
    # And the in-memory index itself was updated, not just the return value.
    assert s.get(item.id).meta.schema_version == META_SCHEMA_VERSION


def test_store_list_refreshes_stale_metadata(tmp_path: Path) -> None:
    """Items served by list() are refreshed too, and pop_dirty reports it."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    media_root = tmp_path / "media"
    rel = "2024/01/01/photo.png"
    (media_root / "2024/01/01").mkdir(parents=True)
    Image.new("RGB", (5, 5)).save(media_root / rel)

    s = MediaStore()
    item = _make_item(
        server_path=rel,
        meta=MediaMetadata(sha256="stale", schema_version=0),
    )
    s.add(item)

    assert s.pop_dirty() is False
    page = s.list(media_root=media_root)
    assert page.items[0].meta.schema_version == META_SCHEMA_VERSION
    assert s.pop_dirty() is True
    # No further mutation on a second read.
    s.list(media_root=media_root)
    assert s.pop_dirty() is False


def test_store_refresh_skips_missing_file(tmp_path: Path) -> None:
    """A stale item whose backing file is gone is left unchanged."""
    s = MediaStore()
    item = _make_item(meta=MediaMetadata(sha256="stale", schema_version=0))
    s.add(item)
    result = s.get(item.id, media_root=tmp_path / "media")
    assert result is not None
    assert result.meta.schema_version == 0
    assert s.pop_dirty() is False


def test_store_list_sort_recent() -> None:
    s = MediaStore()
    older = _make_item(
        filename="old.jpg",
        server_path="2024/01/01/old.jpg",
        meta=MediaMetadata(taken_at=datetime(2020, 1, 1)),
    )
    newer = _make_item(
        filename="new.jpg",
        server_path="2024/01/01/new.jpg",
        meta=MediaMetadata(taken_at=datetime(2024, 1, 1)),
    )
    s.add(older)
    s.add(newer)
    page = s.list(sort="recent")
    assert [it.filename for it in page.items] == ["new.jpg", "old.jpg"]


# ---------------------------------------------------------------------------
# make_thumbnail -- HEIC/HEIF decode, truncated images, video posters
# ---------------------------------------------------------------------------


def test_make_thumbnail_heic(tmp_path: Path) -> None:
    """A synthesized HEIC file decodes and produces a real JPEG thumbnail."""
    try:
        import pillow_heif
        from PIL import Image
    except ImportError:
        pytest.skip("pillow-heif not installed")

    src = tmp_path / "photo.heic"
    heif = pillow_heif.from_pillow(Image.new("RGB", (40, 30), (200, 50, 10)))
    heif.save(src, quality=80)

    dest = tmp_path / "thumb.jpg"
    result = make_thumbnail(src, dest, 32)
    assert result.is_ok
    assert dest.is_file()

    out = Image.open(dest)
    assert out.mode == "RGB"
    assert max(out.size) <= 32


def test_make_thumbnail_truncated_image(tmp_path: Path) -> None:
    """A partially-written JPEG still produces a thumbnail (LOAD_TRUNCATED_IMAGES)."""
    from PIL import Image

    full = tmp_path / "full.jpg"
    Image.new("RGB", (200, 200), (10, 20, 30)).save(full, quality=90)
    data = full.read_bytes()

    truncated = tmp_path / "truncated.jpg"
    truncated.write_bytes(data[: len(data) // 2])

    dest = tmp_path / "thumb.jpg"
    result = make_thumbnail(truncated, dest, 64)
    assert result.is_ok
    assert dest.is_file()


def test_make_thumbnail_undecodable_image_errs(tmp_path: Path) -> None:
    """A file that isn't image data at all fails gracefully, not with a crash."""
    src = tmp_path / "garbage.jpg"
    src.write_bytes(b"this is not an image")
    dest = tmp_path / "thumb.jpg"
    result = make_thumbnail(src, dest, 64)
    assert result.is_err
    assert result.danger_err is IngestError.ExifError
    assert not dest.is_file()


def test_make_thumbnail_video_poster_real_frame(tmp_path: Path) -> None:
    """A real, decodable video yields an actual poster frame, not the placeholder."""
    try:
        import imageio_ffmpeg
    except ImportError:
        pytest.skip("imageio-ffmpeg not installed")
    import subprocess

    from PIL import Image

    src = tmp_path / "clip.mp4"
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            exe,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=64x64:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        capture_output=True,
        check=True,
    )

    dest = tmp_path / "thumb.jpg"
    result = make_thumbnail(src, dest, 128, is_video=True)
    assert result.is_ok
    out = Image.open(dest)
    # The extracted frame is <=64px (source resolution); the drawn placeholder
    # is always exactly `size` x `size` (128x128), so this distinguishes them.
    assert out.size != (128, 128)


def test_make_thumbnail_video_poster_falls_back_on_bad_file(tmp_path: Path) -> None:
    """A file that isn't a real video falls back to the drawn placeholder tile."""
    from PIL import Image

    src = tmp_path / "not_a_video.mp4"
    src.write_bytes(b"\x00" * 32)
    dest = tmp_path / "thumb.jpg"

    result = make_thumbnail(src, dest, 96, is_video=True)
    assert result.is_ok

    out = Image.open(dest)
    assert out.size == (96, 96)
