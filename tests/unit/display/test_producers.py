"""Tests for malmberg_display.slideshow.producers.server and .cache."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from malmberg_display.display.proto import LoadContext
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

    # Pre-create the file at the (no-sha256) cache path so _download is NOT
    # called (tests cache-hit path).
    (tmp_path / "abc" / "nosha").mkdir(parents=True)
    (tmp_path / "abc" / "nosha" / "photo.jpg").write_bytes(b"img")

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


@pytest.mark.asyncio
async def test_server_producer_cache_hit_when_sha256_unchanged(tmp_path: Path) -> None:
    """The same sha256 across two /media fetches serves from cache, no re-GET."""
    media_page = {
        "items": [{"id": "abc", "filename": "photo.jpg", "meta": {"sha256": "aaa111"}}],
        "has_next": False,
    }
    # cache_key is sha256[:12]; "aaa111" is under 12 chars so it is used whole.
    (tmp_path / "abc" / "aaa111").mkdir(parents=True)
    (tmp_path / "abc" / "aaa111" / "photo.jpg").write_bytes(b"img")

    mock_client = AsyncMock()
    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json = MagicMock(return_value=media_page)
    mock_client.get = AsyncMock(return_value=list_resp)
    mock_client.stream = MagicMock(
        side_effect=AssertionError("must not re-download on a cache hit")
    )

    producer = ServerProducer("http://server:8000", tmp_path, mock_client)
    items = [item async for item in producer.items()]
    assert len(items) == 1
    assert items[0].item_id == "abc"


@pytest.mark.asyncio
async def test_server_producer_redownloads_when_sha256_changes(
    tmp_path: Path,
) -> None:
    """A changed meta.sha256 (server-side edit, e.g. permanent rotate) lands
    at a different cache path and is re-downloaded rather than serving the
    stale cached orientation forever."""
    # Old cache entry under the OLD digest -- must be left alone, not read.
    (tmp_path / "abc" / "oldsha0000aa").mkdir(parents=True)
    (tmp_path / "abc" / "oldsha0000aa" / "photo.jpg").write_bytes(b"old-bytes")

    media_page = {
        "items": [
            {
                "id": "abc",
                "filename": "photo.jpg",
                "meta": {"sha256": "newsha0000bb-rest-ignored"},
            }
        ],
        "has_next": False,
    }

    class _FakeStreamResp:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        async def aiter_bytes(self, chunk_size: int = 65536):
            yield b"new-bytes"

    class _FakeStreamCtx:
        async def __aenter__(self) -> "_FakeStreamResp":
            return _FakeStreamResp()

        async def __aexit__(self, *exc: object) -> None:
            return None

    mock_client = AsyncMock()
    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json = MagicMock(return_value=media_page)
    mock_client.get = AsyncMock(return_value=list_resp)
    mock_client.stream = MagicMock(return_value=_FakeStreamCtx())

    producer = ServerProducer("http://server:8000", tmp_path, mock_client)
    items = [item async for item in producer.items()]

    assert len(items) == 1
    new_cache_dir = tmp_path / "abc" / "newsha0000bb"
    # Enumerating must NOT download: the producer is drained end-to-end each
    # cycle, so downloading here would pull the whole library onto the Pi
    # before a single photo is shown (this filled the Pi's card and blacked
    # out the frame). The fetch happens in load(), throttled by the queue.
    assert not (new_cache_dir / "photo.jpg").exists(), (
        "enumeration must not download; fetch belongs in load()"
    )

    await items[0].load(LoadContext(cache_dir=tmp_path))
    assert (new_cache_dir / "photo.jpg").read_bytes() == b"new-bytes"
    # The old cache entry is untouched (left behind, not read or deleted).
    assert (tmp_path / "abc" / "oldsha0000aa" / "photo.jpg").read_bytes() == (
        b"old-bytes"
    )


# ---------------------------------------------------------------------------
# ServerProducer -- single/playlist selection (item_ids) resolves per id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_producer_selected_ids_fetch_info_directly(
    tmp_path: Path,
) -> None:
    """_stream_selected must hit /media/{id}/info per id, not page /media."""
    (tmp_path / "abc" / "nosha").mkdir(parents=True)
    (tmp_path / "abc" / "nosha" / "photo.jpg").write_bytes(b"img")

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

    (tmp_path / "b" / "nosha").mkdir(parents=True)
    (tmp_path / "b" / "nosha" / "b.jpg").write_bytes(b"img")

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


def test_server_producer_evicts_lru_when_cache_over_cap(tmp_path: Path) -> None:
    """The photo cache must stay under its byte cap.

    Unbounded, it grows to the size of the whole library and fills the Pi's
    card, after which nothing downloads and the frame goes dark (this actually
    happened). Least-recently-used files are evicted; the just-downloaded file
    and recently-touched files survive.
    """
    import os

    import httpx

    from malmberg_display.slideshow.producers.server import ServerProducer

    cache = tmp_path / "cache"
    # Three 1 KiB stragglers, oldest first by mtime.
    old = []
    for i in range(3):
        p = cache / f"old{i}" / "k" / f"o{i}.jpg"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x" * 1024)
        os.utime(p, (1000 + i, 1000 + i))
        old.append(p)

    keep = cache / "new" / "k" / "n.jpg"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"y" * 1024)

    prod = ServerProducer("http://x", cache, httpx.AsyncClient(), max_bytes=2048)
    prod._enforce_cache_limit(keep=keep)

    total = sum(p.stat().st_size for p in cache.rglob("*") if p.is_file())
    assert total <= 2048, "cache still over cap after eviction"
    assert keep.is_file(), "just-downloaded file must never be evicted"
    assert not old[0].is_file(), "least-recently-used file should be evicted first"


def test_server_producer_caps_cache_to_a_handful_of_items(tmp_path: Path) -> None:
    """The item cap keeps the cache to a handful of photos.

    The Pi runs off slow flash: a large cache means slow reads and a slow
    directory walk, so we keep only the photos around the current position.
    """
    import os

    import httpx

    from malmberg_display.slideshow.producers.server import ServerProducer

    cache = tmp_path / "cache"
    made = []
    for i in range(10):
        p = cache / f"i{i}" / "k" / f"p{i}.jpg"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"z" * 10)
        os.utime(p, (2000 + i, 2000 + i))  # p0 oldest, p9 newest
        made.append(p)

    prod = ServerProducer(
        "http://x", cache, httpx.AsyncClient(), max_items=3, max_bytes=0
    )
    prod._enforce_cache_limit(keep=made[-1])

    left = [p for p in cache.rglob("*") if p.is_file()]
    assert len(left) == 3, f"expected 3 cached photos, got {len(left)}"
    assert made[-1] in left, "just-downloaded photo must survive"
    assert made[0] not in left, "oldest photo should be evicted first"
