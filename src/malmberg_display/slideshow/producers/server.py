"""ServerProducer: fetches media from a Malmberg Server and yields cached items."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional, Sequence

import httpx

from malmberg_core.logging import get_logger
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext

_log = get_logger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi"}


class CachedItem(Displayable):
    """A Displayable that wraps an already-downloaded local file plus EXIF metadata."""

    def __init__(
        self,
        path: Path,
        item_id: str,
        *,
        taken_at: Optional[datetime] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        camera_model: Optional[str] = None,
        dwell_override_s: Optional[float] = None,
    ) -> None:
        self._path = path
        self._id = item_id
        self._taken_at = taken_at
        self._lat = lat
        self._lon = lon
        self._camera_model = camera_model
        self._dwell_override_s = dwell_override_s
        self._delegate: Optional["Displayable"] = None

    @property
    def item_id(self) -> str:
        return self._id

    def __repr__(self) -> str:
        """Friendly name (the filename) for status/history readouts."""
        return self._path.name

    async def load(self, ctx: LoadContext) -> None:
        """Instantiate the appropriate Displayable for the cached file type."""
        suffix = self._path.suffix.lower()
        if suffix in _VIDEO_SUFFIXES:
            from malmberg_display.display.video import VideoDisplay

            d = VideoDisplay(self._path)
        else:
            from malmberg_display.display.picture import PictureDisplay

            d = PictureDisplay(
                self._path,
                taken_at=self._taken_at,
                lat=self._lat,
                lon=self._lon,
                camera_model=self._camera_model,
                dwell_override_s=self._dwell_override_s,
            )
        await d.load(ctx)
        self._delegate = d

    async def display(self, ctx: DisplayContext) -> None:
        if self._delegate is None:
            raise RuntimeError("CachedItem.load() must be called before display()")
        await self._delegate.display(ctx)


class ServerProducer:
    """Async generator that fetches media pages from the server and yields CachedItems.

    Downloads are cached under *cache_dir* keyed by item id.  Already-cached
    files are served directly without re-downloading.  Yields items in server
    list order; the caller (InfiniteProducer or Slideshow) is responsible for
    shuffling.
    """

    def __init__(
        self,
        server_url: str,
        cache_dir: Path,
        http_client: httpx.AsyncClient,
        item_ids: Optional[Sequence[str]] = None,
        max_bytes: int = 4 * 1024 * 1024 * 1024,
    ) -> None:
        self._url = server_url.rstrip("/")
        self._cache_dir = cache_dir
        self._client = http_client
        # When set, play only these item ids in this order (a programmed
        # slideshow or a single "display this photo now"); otherwise play all.
        self._item_ids = list(item_ids) if item_ids is not None else None
        # Hard cap on the on-disk cache. Without this the cache grows to the
        # size of the entire library and fills the Pi's card, after which no
        # photo can be downloaded and the frame goes dark.
        self._max_bytes = max_bytes

    def _enforce_cache_limit(self, keep: Path) -> None:
        """Evict least-recently-used cached files until under ``max_bytes``.

        *keep* is the file just downloaded; it is never evicted.  Recency is
        the file mtime, which ``_item_from_raw`` refreshes on every cache hit,
        so files still in rotation survive and stale ones (including cache
        dirs orphaned by a server-side rotate) are reclaimed first.
        """
        if self._max_bytes <= 0:
            return
        entries: list[tuple[float, int, Path]] = []
        total = 0
        for path in self._cache_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        if total <= self._max_bytes:
            return

        entries.sort(key=lambda e: e[0])  # least recently used first
        freed = 0
        for _mtime, size, path in entries:
            if total - freed <= self._max_bytes:
                break
            if path == keep:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            freed += size
        _log.info(
            "Photo cache over %d bytes; evicted %d bytes of least-recently-used "
            "files (cache is disposable, files re-download on demand)",
            self._max_bytes,
            freed,
        )
        # Drop the now-empty per-item / per-sha256 directories left behind.
        for path in sorted(
            self._cache_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True
        ):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass

    async def items(self) -> AsyncGenerator[CachedItem, None]:
        """Yield CachedItems -- either the whole library or a specific id list."""
        if self._item_ids is None:
            async for item in self._stream_all():
                yield item
        else:
            async for item in self._stream_selected(self._item_ids):
                yield item

    async def _stream_all(self) -> AsyncGenerator[CachedItem, None]:
        """Yield every media item, streaming page by page for fast startup."""
        page = 1
        while True:
            data = await self._fetch_page(page)
            if data is None:
                return
            for raw in data.get("items", []):
                item = await self._item_from_raw(raw)
                if item is not None:
                    yield item
            if not data.get("has_next", False):
                break
            page += 1

    async def _stream_selected(
        self, item_ids: Sequence[str]
    ) -> AsyncGenerator[CachedItem, None]:
        """Yield only *item_ids*, in order, resolving each directly by id.

        Fetches ``/media/{id}/info`` per id instead of paging the whole
        library index: a transient failure or a missing id only drops that
        one item, rather than silently yielding nothing for the entire
        selection (which previously left the display frozen on the last
        shown photo -- async_load_infinite retries an empty cycle forever).
        """
        for item_id in item_ids:
            raw = await self._fetch_info(item_id)
            if raw is None:
                continue
            item = await self._item_from_raw(raw)
            if item is not None:
                yield item

    async def _fetch_info(self, item_id: str) -> Optional[dict]:
        """GET /media/{item_id}/info; None on request failure or 404."""
        try:
            resp = await self._client.get(
                f"{self._url}/media/{item_id}/info", timeout=10.0
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            _log.warning("Server request failed (item %s): %s", item_id, exc)
            return None
        return resp.json()

    async def _fetch_page(self, page: int) -> Optional[dict]:
        """GET one /media page; None on request failure."""
        try:
            resp = await self._client.get(
                f"{self._url}/media",
                params={"page": page, "page_size": 100},
                timeout=10.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            _log.warning("Server request failed (page %d): %s", page, exc)
            return None
        return resp.json()

    async def _item_from_raw(self, raw: dict) -> Optional[CachedItem]:
        """Build (downloading if needed) a CachedItem from a raw media record.

        The cache path is keyed by both item id and a sha256 prefix (from
        meta.sha256, which the server recomputes on every content-changing
        edit -- e.g. a permanent rotate/flip). A server-side edit therefore
        changes the digest, which changes the cache path, so the file is
        re-downloaded instead of silently serving the stale cached
        orientation forever. Old per-sha256 cache dirs for a since-edited
        item are simply left behind (harmless, never read again).
        """
        item_id = raw.get("id", "")
        filename = raw.get("filename", "unknown")
        meta = raw.get("meta") or {}
        digest = meta.get("sha256") or ""
        cache_key = digest[:12] if digest else "nosha"
        cached = self._cache_dir / item_id / cache_key / filename
        if cached.is_file():
            # Cache hit: bump mtime so this file counts as recently used and
            # survives LRU eviction while it is still in rotation.
            try:
                os.utime(cached, None)
            except OSError:
                pass
        else:
            ok = await self._download(item_id, filename, cached)
            if not ok:
                return None
            self._enforce_cache_limit(keep=cached)
        # effective_taken_at/effective_lat/effective_lon (computed server-side
        # from MediaMetadata) prefer a manual override over raw EXIF, so a
        # manually-dated/-located photo shows the right caption on the frame
        # with no display-side changes needed beyond reading these fields
        # instead of the raw taken_at/lat/lon.
        taken_at: Optional[datetime] = None
        if ts := meta.get("effective_taken_at"):
            try:
                taken_at = datetime.fromisoformat(ts)
            except ValueError:
                pass
        return CachedItem(
            cached,
            item_id,
            taken_at=taken_at,
            lat=meta.get("effective_lat"),
            lon=meta.get("effective_lon"),
            camera_model=meta.get("camera_model"),
            dwell_override_s=raw.get("dwell_override_s"),
        )

    async def _download(self, item_id: str, filename: str, dest: Path) -> bool:
        """Download /media/{item_id} to *dest*.  Returns True on success."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        try:
            async with self._client.stream(
                "GET", f"{self._url}/media/{item_id}", timeout=60.0
            ) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
            tmp.rename(dest)
            _log.debug("Downloaded %s -> %s", item_id, dest)
            return True
        except (httpx.HTTPError, OSError) as exc:
            _log.warning("Failed to download %s (%s): %s", item_id, filename, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            return False
