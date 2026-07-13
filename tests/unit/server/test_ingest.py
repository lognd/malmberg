"""Tests for malmberg_server.ingest."""

from __future__ import annotations

import math
import random
import sys
from datetime import datetime
from pathlib import Path

import pytest

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.ingest import gazetteer
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import (
    META_SCHEMA_VERSION,
    extract_exif,
    make_thumbnail,
    reverse_geocode,
    sha256_of_file,
    transform_image,
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
# reverse_geocode
# ---------------------------------------------------------------------------


def test_reverse_geocode_known_coordinate() -> None:
    """A known Tampa-area coordinate resolves to a plausible Florida label."""
    pytest.importorskip("numpy")
    gazetteer.configure(None)
    place = reverse_geocode(27.98, -82.82)
    assert place is not None
    assert "Florida" in place


def test_reverse_geocode_none_coords() -> None:
    assert reverse_geocode(None, None) is None
    assert reverse_geocode(1.0, None) is None


def test_reverse_geocode_missing_numpy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the geocode extra not being installed: best-effort None, no raise."""
    gazetteer.configure(None)
    monkeypatch.setitem(sys.modules, "numpy", None)
    try:
        assert reverse_geocode(27.98, -82.82) is None
    finally:
        gazetteer.configure(None)


def test_reverse_geocode_distinguishes_batam_from_singapore() -> None:
    """The bug this dataset exists to fix: reverse_geocoder's bundled city list
    has no Batam, so every photo on the island came back "Singapore"."""
    pytest.importorskip("numpy")
    gazetteer.configure(None)
    assert "Batam" in (reverse_geocode(1.19, 104.10) or "")  # Nongsa, Batam
    assert "Batam" in (reverse_geocode(1.14, 103.95) or "")  # Sekupang, Batam
    assert "Singapore" in (reverse_geocode(1.29, 103.85) or "")


def test_reverse_geocode_prefers_the_dominant_city_only() -> None:
    """A city swallows its own districts; a town does not swallow its neighbour."""
    pytest.importorskip("numpy")
    gazetteer.configure(None)
    # Ang Mo Kio is a new town inside a 20x bigger Singapore -> Singapore.
    assert "Singapore" in (reverse_geocode(1.35, 103.82) or "")
    # Oxelosund sits next to a merely 3x bigger Nykoping -> it keeps its name.
    assert "Oxel" in (reverse_geocode(58.67, 17.10) or "")


def test_reverse_geocode_nowhere_gets_no_label() -> None:
    """Mid-ocean: no label beats a misleading one 200 km away."""
    pytest.importorskip("numpy")
    gazetteer.configure(None)
    assert reverse_geocode(0.0, -30.0) is None


def test_gazetteer_extra_csv_wins_for_nearby_photos(tmp_path) -> None:
    """The user's own places (a cabin, a farm) beat any city near them.

    A custom entry has no population, so the dominance rule would otherwise
    hand its photos straight to the nearest real city -- exactly backwards.
    """
    pytest.importorskip("numpy")
    (tmp_path / gazetteer.EXTRA_CSV_NAME).write_text(
        "lat,lon,name,admin1,cc,population\n"
        "27.9805,-82.8210,Grandma's house,Florida,US,0\n",
        encoding="utf8",
    )
    gazetteer.configure(tmp_path)
    try:
        assert reverse_geocode(27.9805, -82.8210) == "Grandma's house, Florida, US"
        # ...but only near it: a photo across town is still Clearwater.
        assert "Clearwater" in (reverse_geocode(27.95, -82.75) or "")
    finally:
        gazetteer.configure(None)


def test_gazetteer_ignores_a_malformed_extra_row(tmp_path) -> None:
    """A typo in the user's file must not take geocoding down for the library."""
    pytest.importorskip("numpy")
    (tmp_path / gazetteer.EXTRA_CSV_NAME).write_text(
        "lat,lon,name,admin1,cc,population\nnot-a-number,-82.8,Broken,Florida,US,0\n",
        encoding="utf8",
    )
    gazetteer.configure(tmp_path)
    try:
        assert "Clearwater" in (reverse_geocode(27.98, -82.82) or "")
    finally:
        gazetteer.configure(None)


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


def test_store_stats_by_month() -> None:
    s = MediaStore()
    dates = [
        datetime(2006, 3, 5),
        datetime(2006, 3, 20),
        datetime(2006, 7, 1),
        datetime(2024, 1, 15),
    ]
    for i, dt in enumerate(dates):
        s.add(
            _make_item(
                filename=f"{i}.jpg",
                server_path=f"p/{i}.jpg",
                meta=MediaMetadata(sha256=f"h{i}", taken_at=dt),
            )
        )
    stats = s.stats()
    assert stats["by_year"] == {"2006": 3, "2024": 1}
    assert stats["by_month"] == {"2006-03": 2, "2006-07": 1, "2024-01": 1}


def test_store_matches_query_place() -> None:
    s = MediaStore()
    s.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(sha256="h1", place="Tampa, Florida, US"),
        )
    )
    s.add(_make_item(filename="b.jpg", server_path="p/b.jpg"))
    page = s.list(q="tampa")
    assert page.total == 1
    assert page.items[0].filename == "a.jpg"


def test_store_matches_query_month() -> None:
    s = MediaStore()
    s.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(sha256="h1", taken_at=datetime(2006, 7, 4)),
        )
    )
    s.add(
        _make_item(
            filename="b.jpg",
            server_path="p/b.jpg",
            meta=MediaMetadata(sha256="h2", taken_at=datetime(2006, 8, 1)),
        )
    )
    s.add(_make_item(filename="c.jpg", server_path="p/c.jpg"))
    page = s.list(q="2006-07")
    assert page.total == 1
    assert page.items[0].filename == "a.jpg"


def test_store_stats_by_place() -> None:
    s = MediaStore()
    s.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(sha256="h1", place="Tampa, Florida, US"),
        )
    )
    s.add(
        _make_item(
            filename="b.jpg",
            server_path="p/b.jpg",
            meta=MediaMetadata(sha256="h2", place="Tampa, Florida, US"),
        )
    )
    s.add(
        _make_item(
            filename="c.jpg",
            server_path="p/c.jpg",
            meta=MediaMetadata(sha256="h3", place="Orlando, Florida, US"),
        )
    )
    s.add(_make_item(filename="d.jpg", server_path="p/d.jpg"))
    stats = s.stats()
    assert stats["by_place"] == {
        "Tampa, Florida, US": 2,
        "Orlando, Florida, US": 1,
    }


def test_store_places_autocomplete() -> None:
    s = MediaStore()
    s.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(sha256="h1", place="Tampa, Florida, US"),
        )
    )
    s.add(
        _make_item(
            filename="b.jpg",
            server_path="p/b.jpg",
            meta=MediaMetadata(sha256="h2", place="Orlando, Florida, US"),
        )
    )
    assert s.places(q="tam") == ["Tampa, Florida, US"]
    assert set(s.places(q="florida")) == {
        "Tampa, Florida, US",
        "Orlando, Florida, US",
    }
    assert s.places(q="nowhere") == []


def test_store_and_filters_time_and_place() -> None:
    """q_time AND q_place returns only items matching BOTH, not either."""
    from malmberg_server.faces.people import Person, PersonStore

    people = PersonStore()
    person = Person(name="Alice")
    people._people[person.id] = person

    s = MediaStore()
    s.add(
        _make_item(
            filename="a.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(
                sha256="h1", taken_at=datetime(2006, 7, 4), place="Tampa, FL"
            ),
            person_ids=[person.id],
        )
    )
    s.add(
        _make_item(
            filename="b.jpg",
            server_path="p/b.jpg",
            meta=MediaMetadata(
                sha256="h2", taken_at=datetime(2006, 7, 4), place="Orlando, FL"
            ),
        )
    )
    s.add(
        _make_item(
            filename="c.jpg",
            server_path="p/c.jpg",
            meta=MediaMetadata(
                sha256="h3", taken_at=datetime(2010, 1, 1), place="Tampa, FL"
            ),
        )
    )

    page = s.list(q_time="2006", q_place="Tampa")
    assert page.total == 1
    assert page.items[0].filename == "a.jpg"

    # Person filter AND'd with time.
    page2 = s.list(q_time="2006", q_person="Alice", people=people)
    assert page2.total == 1
    assert page2.items[0].filename == "a.jpg"

    # No filters given -> everything.
    assert s.list().total == 3

    # Filter with no match -> empty.
    assert s.list(q_time="2006", q_place="Nowhere").total == 0


def test_store_unsorted_filters() -> None:
    """q_time/q_place='unsorted' selects exactly the items missing that field."""
    s = MediaStore()
    s.add(
        _make_item(
            filename="dated_placed.jpg",
            server_path="p/a.jpg",
            meta=MediaMetadata(
                sha256="h1", taken_at=datetime(2006, 7, 4), place="Tampa, FL"
            ),
        )
    )
    s.add(  # a screenshot: no EXIF date, no GPS
        _make_item(
            filename="screenshot.png",
            server_path="p/b.png",
            meta=MediaMetadata(sha256="h2"),
        )
    )
    s.add(  # dated but never located
        _make_item(
            filename="dated_only.jpg",
            server_path="p/c.jpg",
            meta=MediaMetadata(sha256="h3", taken_at=datetime(2010, 1, 1)),
        )
    )

    undated = s.list(q_time="unsorted")
    assert [it.filename for it in undated.items] == ["screenshot.png"]

    unplaced = s.list(q_place="unsorted")
    assert sorted(it.filename for it in unplaced.items) == [
        "dated_only.jpg",
        "screenshot.png",
    ]

    # AND'd with each other, and case-insensitive.
    both = s.list(q_time="UNSORTED", q_place="unsorted")
    assert [it.filename for it in both.items] == ["screenshot.png"]

    # A manual override counts as sorted: it fills the effective_* field.
    item = next(i for i in s.list().items if i.filename == "screenshot.png")
    s.patch(item.id, {"meta": item.meta.model_copy(update={"manual_place": "Home"})})
    assert [it.filename for it in s.list(q_place="unsorted").items] == [
        "dated_only.jpg"
    ]

    stats = s.stats()
    assert stats["undated"] == 1
    assert stats["unplaced"] == 1


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


# ---------------------------------------------------------------------------
# transform_image -- permanent rotate/flip, with EXIF (GPS/date) preservation
# ---------------------------------------------------------------------------


def _make_jpeg_with_exif(path: Path, size=(80, 40), orientation: int = 1) -> None:
    """Write a JPEG with GPS + DateTimeOriginal + Make/Model EXIF for testing.

    A solid red block fills the top-left quadrant, blue fills the rest, so a
    rotate/flip is verifiable by checking which quadrant reads red afterward
    (a single corner pixel is too easily washed out by JPEG compression).
    """
    from PIL import ExifTags, Image

    img = Image.new("RGB", size, (0, 0, 255))
    half_w, half_h = size[0] // 2, size[1] // 2
    for x in range(half_w):
        for y in range(half_h):
            img.putpixel((x, y), (255, 0, 0))
    exif = img.getexif()
    exif[0x0112] = orientation  # Orientation
    exif[271] = "TestMake"  # Make
    exif[272] = "TestModel"  # Model
    exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
    exif_ifd[36867] = "2020:01:02 03:04:05"  # DateTimeOriginal
    gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps_ifd[1] = "N"
    gps_ifd[2] = (27.0, 58.0, 48.0)
    gps_ifd[3] = "W"
    gps_ifd[4] = (82.0, 49.0, 12.0)
    img.save(path, exif=exif.tobytes())


def test_transform_image_rotate_swaps_dimensions_and_pixels(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "photo.jpg"
    _make_jpeg_with_exif(path)

    result = transform_image(path, rotate=90)
    assert result.is_ok

    out = Image.open(path)
    assert out.size == (40, 80)  # width/height swapped
    # 90 CW: the original top-left (red) quadrant moves to the top-right.
    top_right = out.getpixel((30, 10))
    assert top_right[0] > top_right[2]


def test_transform_image_preserves_gps_date_and_camera(tmp_path: Path) -> None:
    """The key regression: EXIF GPS/date/camera must survive a rotate, in the
    FILE itself, not just the in-memory index -- MediaStore re-extracts from
    disk on schema bumps."""
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_exif(path)

    before = extract_exif(path)
    assert before.is_ok
    before_meta = before.danger_ok
    assert before_meta.lat is not None
    assert before_meta.lon is not None
    assert before_meta.taken_at is not None
    assert before_meta.camera_model == "TestMake TestModel"

    result = transform_image(path, rotate=90)
    assert result.is_ok

    after = extract_exif(path)
    assert after.is_ok
    after_meta = after.danger_ok
    assert after_meta.width == 40
    assert after_meta.height == 80
    assert after_meta.lat == pytest.approx(before_meta.lat, abs=1e-4)
    assert after_meta.lon == pytest.approx(before_meta.lon, abs=1e-4)
    assert after_meta.taken_at == before_meta.taken_at
    assert after_meta.camera_model == before_meta.camera_model
    # Content changed, so the digest must differ.
    assert after_meta.sha256 != before_meta.sha256


def test_transform_image_normalizes_orientation_tag(tmp_path: Path) -> None:
    """A source file with a non-1 Orientation tag ends up baked-in and normal."""
    from PIL import ExifTags, Image

    path = tmp_path / "photo.jpg"
    _make_jpeg_with_exif(path, orientation=6)  # rotated 90 CW display

    result = transform_image(path, rotate=0)
    assert result.is_ok

    out = Image.open(path)
    out_exif = out.getexif()
    assert out_exif.get(0x0112, 1) == 1
    # exif_transpose baked orientation=6 (rotate 270 CW display) into pixels:
    # dimensions swap relative to the raw stored size.
    assert out.size == (40, 80)
    # ImageOps consumers won't be confused: no ExifTags.Base.Orientation left.
    assert ExifTags.Base.Orientation not in out.getexif() or (
        out.getexif()[ExifTags.Base.Orientation] == 1
    )


def test_transform_image_flip_horizontal(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "photo.jpg"
    _make_jpeg_with_exif(path)
    result = transform_image(path, flip="h")
    assert result.is_ok
    out = Image.open(path)
    assert out.size == (80, 40)
    # The red top-left quadrant is now the top-right quadrant.
    top_right = out.getpixel((60, 10))
    assert top_right[0] > top_right[2]


def test_transform_image_rejects_video(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    result = transform_image(path, rotate=90)
    assert result.is_err
    assert result.danger_err is IngestError.UnsupportedMedia


def test_transform_image_undecodable_file(tmp_path: Path) -> None:
    path = tmp_path / "garbage.jpg"
    path.write_bytes(b"this is not an image")
    result = transform_image(path, rotate=90)
    assert result.is_err
    assert result.danger_err is IngestError.ExifError


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


def test_gazetteer_index_agrees_with_an_exhaustive_scan() -> None:
    """The cell index is an optimization, so it must change nothing.

    The lookup used to scan all 225k places per photo, which turned a
    12,760-photo re-geocode sweep into 3 billion distance computations on a
    4-core NAS. Bucketing into 1-degree cells made it ~450x faster; this pins
    that it still picks the same place, including at the poles and across the
    antimeridian, where the cell arithmetic is easy to get subtly wrong.
    """
    np = pytest.importorskip("numpy")
    gazetteer.configure(None)
    xyz, pop, places, _cells = gazetteer._build_index()

    def exhaustive(lat: float, lon: float):
        rlat, rlon = math.radians(lat), math.radians(lon)
        probe = np.array(
            [
                math.cos(rlat) * math.cos(rlon),
                math.cos(rlat) * math.sin(rlon),
                math.sin(rlat),
            ]
        )
        dot = np.clip(xyz @ probe, -1.0, 1.0)
        nearest = int(np.argmax(dot))
        km = float(np.arccos(dot[nearest])) * gazetteer._EARTH_R_KM
        if km > gazetteer._CANDIDATE_KM:
            return None
        cutoff = math.cos((km + gazetteer._NEARBY_SLACK_KM) / gazetteer._EARTH_R_KM)
        near = np.flatnonzero(dot >= cutoff)
        dominant = near[
            pop[near] > max(float(pop[nearest]) * gazetteer._DOMINANCE, 0.0)
        ]
        if dominant.size:
            best = dominant[int(np.lexsort((-dot[dominant], -pop[dominant]))[0])]
            return places[int(best)]
        return places[nearest]

    rng = random.Random(7)
    probes = [(rng.uniform(-85.0, 85.0), rng.uniform(-180.0, 180.0)) for _ in range(60)]
    probes += [(78.22, 15.65), (-16.5, -179.9), (1.19, 104.10), (-89.0, 179.99)]
    for lat, lon in probes:
        got = gazetteer.lookup(lat, lon)
        want = exhaustive(lat, lon)
        assert (got.label if got else None) == (want.label if want else None), (
            lat,
            lon,
        )
