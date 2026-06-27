"""Tests for malmberg_core.models."""

from __future__ import annotations

from malmberg_core.models import MediaItem, MediaMetadata, MediaPage, Tag


def test_tag_round_trip() -> None:
    t = Tag(name="Test", id="server", version="0.1.0", mac="AA:BB:CC:DD:EE:FF")
    assert t.id == "server"
    assert t.model_dump()["id"] == "server"


def test_media_item_defaults() -> None:
    item = MediaItem(
        kind="image", filename="photo.jpg", server_path="2024/01/01/photo.jpg"
    )
    assert item.id  # uuid auto-assigned
    assert not item.do_not_display
    assert item.hide_policy == "delete"
    assert item.dwell_override_s is None
    assert item.tags == []


def test_media_metadata_defaults() -> None:
    m = MediaMetadata()
    assert m.taken_at is None
    assert m.camera_model is None
    assert m.sha256 == ""


def test_media_page() -> None:
    items = [
        MediaItem(kind="image", filename=f"{i}.jpg", server_path=f"2024/01/01/{i}.jpg")
        for i in range(3)
    ]
    page = MediaPage(items=items, total=10, page=1, page_size=3, has_next=True)
    assert len(page.items) == 3
    assert page.has_next
