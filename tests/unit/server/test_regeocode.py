"""Tests for malmberg_server.ingest.regeocode (the background place refresh)."""

from __future__ import annotations

from malmberg_core.models import MediaItem, MediaMetadata
from malmberg_server.ingest.gazetteer import GAZETTEER_VERSION
from malmberg_server.ingest.regeocode import regeocode_all, stale_ids
from malmberg_server.ingest.store import MediaStore


def _item(item_id: str, **meta) -> MediaItem:
    return MediaItem(
        id=item_id,
        kind="image",
        filename=f"{item_id}.jpg",
        server_path=f"p/{item_id}.jpg",
        meta=MediaMetadata(sha256=item_id, **meta),
    )


def test_stale_ids_only_items_with_coords_behind_the_version() -> None:
    store = MediaStore()
    store.add(_item("old", lat=1.19, lon=104.10, place="Singapore, SG"))
    store.add(_item("nocoords", place="Somewhere"))
    store.add(_item("current", lat=1.19, lon=104.10, geo_version=GAZETTEER_VERSION))
    assert stale_ids(store) == ["old"]


def test_regeocode_fixes_the_batam_photos() -> None:
    """The bug that motivated all of this: photos on Batam labelled Singapore."""
    import pytest

    pytest.importorskip("numpy")
    store = MediaStore()
    store.add(_item("batam", lat=1.19, lon=104.10, place="Singapore, SG"))

    visited, changed = regeocode_all(store)
    assert (visited, changed) == (1, 1)

    meta = store.get("batam").meta
    assert "Batam" in meta.place
    assert meta.geo_version == GAZETTEER_VERSION
    # Idempotent: a second sweep has nothing left to do.
    assert regeocode_all(store) == (0, 0)


def test_regeocode_never_touches_a_manual_place() -> None:
    """Silently rewriting what someone typed is the one unforgivable move."""
    import pytest

    pytest.importorskip("numpy")
    store = MediaStore()
    store.add(
        _item(
            "tagged",
            lat=1.19,
            lon=104.10,
            place="Singapore, SG",
            manual_place="Turi Beach Resort",
        )
    )
    regeocode_all(store)
    meta = store.get("tagged").meta
    assert meta.manual_place == "Turi Beach Resort"
    assert meta.effective_place == "Turi Beach Resort"
    assert "Batam" in meta.place  # the derived label is still corrected
