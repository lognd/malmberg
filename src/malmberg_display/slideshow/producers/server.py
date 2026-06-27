"""ServerProducer: fetches media from a Malmberg Server and yields cached items."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Optional

import httpx

from malmberg_core.logging import get_logger
from malmberg_display.display.proto import DisplayContext, LoadContext

if TYPE_CHECKING:
    from malmberg_display.display.proto import Displayable

_log = get_logger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi"}


class CachedItem:
    """A Displayable that wraps an already-downloaded local file."""

    def __init__(self, path: Path, item_id: str) -> None:
        self._path = path
        self._id = item_id
        self._delegate: Optional["Displayable"] = None

    @property
    def item_id(self) -> str:
        return self._id

    async def load(self, ctx: LoadContext) -> None:
        """Instantiate the appropriate Displayable for the cached file type."""
        suffix = self._path.suffix.lower()
        if suffix in _VIDEO_SUFFIXES:
            from malmberg_display.display.video import VideoDisplay

            d = VideoDisplay(self._path)
        else:
            from malmberg_display.display.picture import PictureDisplay

            d = PictureDisplay(self._path)
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
    ) -> None:
        self._url = server_url.rstrip("/")
        self._cache_dir = cache_dir
        self._client = http_client

    async def items(self) -> AsyncGenerator[CachedItem, None]:
        """Yield one CachedItem per media item returned by the server."""
        page = 1
        while True:
            try:
                resp = await self._client.get(
                    f"{self._url}/media",
                    params={"page": page, "page_size": 50},
                    timeout=10.0,
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                _log.warning("Server request failed (page %d): %s", page, exc)
                return

            data = resp.json()
            for raw in data.get("items", []):
                item_id = raw.get("id", "")
                filename = raw.get("filename", "unknown")
                cached = self._cache_dir / item_id / filename
                if not cached.is_file():
                    ok = await self._download(item_id, filename, cached)
                    if not ok:
                        continue
                yield CachedItem(cached, item_id)

            if not data.get("has_next", False):
                break
            page += 1

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
