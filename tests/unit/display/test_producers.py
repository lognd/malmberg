"""Tests for malmberg_display.slideshow.producers.server and .cache."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from malmberg_display.slideshow.producers.cache import CacheProducer
from malmberg_display.slideshow.producers.server import CachedItem, ServerProducer

# ---------------------------------------------------------------------------
# CachedItem
# ---------------------------------------------------------------------------


def test_cached_item_properties(tmp_path: Path) -> None:
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"jpg")
    item = CachedItem(f, "abc123")
    assert item.item_id == "abc123"


# ---------------------------------------------------------------------------
# CacheProducer -- scan mode
# ---------------------------------------------------------------------------


def test_cache_producer_scan(tmp_path: Path) -> None:
    (tmp_path / "id1").mkdir()
    (tmp_path / "id1" / "img.jpg").write_bytes(b"x")
    (tmp_path / "id2").mkdir()
    (tmp_path / "id2" / "vid.mp4").write_bytes(b"y")

    producer = CacheProducer(tmp_path)
    items = list(producer.items())
    assert len(items) == 2
    ids = {i.item_id for i in items}
    assert ids == {"id1", "id2"}


def test_cache_producer_empty_dir(tmp_path: Path) -> None:
    producer = CacheProducer(tmp_path)
    assert list(producer.items()) == []


def test_cache_producer_missing_dir(tmp_path: Path) -> None:
    producer = CacheProducer(tmp_path / "nonexistent")
    assert list(producer.items()) == []


# ---------------------------------------------------------------------------
# CacheProducer -- index mode
# ---------------------------------------------------------------------------


def test_cache_producer_from_index(tmp_path: Path) -> None:
    (tmp_path / "id1").mkdir()
    (tmp_path / "id1" / "img.jpg").write_bytes(b"x")
    index = [{"id": "id1", "filename": "img.jpg"}]
    (tmp_path / "cache-index.json").write_text(json.dumps(index))

    producer = CacheProducer(tmp_path)
    items = list(producer.items())
    assert len(items) == 1
    assert items[0].item_id == "id1"


def test_cache_producer_index_missing_file_skips(tmp_path: Path) -> None:
    index = [{"id": "ghost", "filename": "nope.jpg"}]
    (tmp_path / "cache-index.json").write_text(json.dumps(index))

    producer = CacheProducer(tmp_path)
    items = list(producer.items())
    assert items == []


def test_cache_producer_write_index(tmp_path: Path) -> None:
    (tmp_path / "id1").mkdir()
    f = tmp_path / "id1" / "pic.jpg"
    f.write_bytes(b"x")
    item = CachedItem(f, "id1")

    producer = CacheProducer(tmp_path)
    producer.write_index([item])

    idx_path = tmp_path / "cache-index.json"
    assert idx_path.is_file()
    data = json.loads(idx_path.read_text())
    assert data[0]["id"] == "id1"
    assert data[0]["filename"] == "pic.jpg"


# ---------------------------------------------------------------------------
# ServerProducer -- download path (mocked httpx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_producer_yields_cached_items(tmp_path: Path) -> None:
    media_page = {
        "items": [{"id": "abc", "filename": "photo.jpg"}],
        "has_next": False,
    }

    mock_client = AsyncMock()
    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json = MagicMock(return_value=media_page)

    # Pre-create the file so _download is NOT called (tests cache-hit path).
    (tmp_path / "abc").mkdir()
    (tmp_path / "abc" / "photo.jpg").write_bytes(b"img")

    mock_client.get = AsyncMock(return_value=list_resp)

    producer = ServerProducer("http://server:8000", tmp_path, mock_client)
    items = [item async for item in producer.items()]
    assert len(items) == 1
    assert items[0].item_id == "abc"


@pytest.mark.asyncio
async def test_server_producer_skips_on_http_error(tmp_path: Path) -> None:
    import httpx

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

    producer = ServerProducer("http://server:8000", tmp_path, mock_client)
    items = [item async for item in producer.items()]
    assert items == []


# ---------------------------------------------------------------------------
# ServerProducer -- single/playlist selection (item_ids) resolves per id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_producer_selected_ids_fetch_info_directly(
    tmp_path: Path,
) -> None:
    """_stream_selected must hit /media/{id}/info per id, not page /media."""
    (tmp_path / "abc").mkdir()
    (tmp_path / "abc" / "photo.jpg").write_bytes(b"img")

    info_resp = MagicMock()
    info_resp.raise_for_status = MagicMock()
    info_resp.json = MagicMock(return_value={"id": "abc", "filename": "photo.jpg"})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=info_resp)

    producer = ServerProducer(
        "http://server:8000", tmp_path, mock_client, item_ids=["abc"]
    )
    items = [item async for item in producer.items()]

    assert len(items) == 1
    assert items[0].item_id == "abc"
    called_url = mock_client.get.call_args.args[0]
    assert called_url == "http://server:8000/media/abc/info"


@pytest.mark.asyncio
async def test_server_producer_selected_ids_survive_one_failure(
    tmp_path: Path,
) -> None:
    """A transient failure resolving one requested id must not drop the rest.

    Regression: the old paging-based _stream_selected resolved every id from
    a single full-library scan, so ANY page fetch failure (even a transient
    one) silently yielded nothing for the whole selection -- leaving the
    display frozen forever on the last shown photo (async_load_infinite
    retries an empty cycle indefinitely rather than terminating).
    """
    import httpx

    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "b.jpg").write_bytes(b"img")

    ok_resp = MagicMock()
    ok_resp.raise_for_status = MagicMock()
    ok_resp.json = MagicMock(return_value={"id": "b", "filename": "b.jpg"})

    async def _get(url: str, **kwargs: object) -> MagicMock:
        if url.endswith("/media/a/info"):
            raise httpx.ConnectError("transient failure fetching a")
        return ok_resp

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=_get)

    producer = ServerProducer(
        "http://server:8000", tmp_path, mock_client, item_ids=["a", "b"]
    )
    items = [item async for item in producer.items()]

    assert [i.item_id for i in items] == ["b"], (
        "a transient failure resolving id 'a' incorrectly dropped id 'b' too"
    )
