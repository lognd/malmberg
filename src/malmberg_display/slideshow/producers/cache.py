"""CacheProducer: serves media from local cache for offline/degraded mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator, Optional

from malmberg_core.logging import get_logger
from malmberg_display.slideshow.producers.server import CachedItem

_log = get_logger(__name__)

_INDEX_NAME = "cache-index.json"


class CacheProducer:
    """Yields CachedItems from a local cache directory.

    The cache directory layout written by ServerProducer is::

        cache_dir/
            <item_id>/
                <filename>
            cache-index.json   (optional fast-path index)

    If ``cache-index.json`` is present it is read; otherwise the directory is
    scanned directly.  Items are yielded in the order they appear in the index
    (or filesystem order when scanning).  Callers should wrap with
    ``load_infinite`` for loop-forever behaviour.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir

    def items(self) -> Generator[CachedItem, None, None]:
        """Yield CachedItems from the cache; logs and skips bad entries."""
        index_path = self._cache_dir / _INDEX_NAME
        if index_path.is_file():
            yield from self._from_index(index_path)
        else:
            yield from self._scan()

    def _from_index(self, index_path: Path) -> Generator[CachedItem, None, None]:
        try:
            entries: list[dict] = json.loads(index_path.read_text())
        except (OSError, ValueError) as exc:
            _log.warning(
                "Could not read cache index %s: %s -- falling back to scan",
                index_path,
                exc,
            )
            yield from self._scan()
            return

        for entry in entries:
            item_id: Optional[str] = entry.get("id")
            filename: Optional[str] = entry.get("filename")
            if not item_id or not filename:
                continue
            path = self._cache_dir / item_id / filename
            if path.is_file():
                yield CachedItem(path, item_id)
            else:
                _log.debug("Cached file missing: %s", path)

    def _scan(self) -> Generator[CachedItem, None, None]:
        if not self._cache_dir.is_dir():
            _log.warning("Cache directory does not exist: %s", self._cache_dir)
            return
        for subdir in sorted(self._cache_dir.iterdir()):
            if not subdir.is_dir():
                continue
            for f in sorted(subdir.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    yield CachedItem(f, subdir.name)

    def write_index(self, items: list[CachedItem]) -> None:
        """Persist a cache-index.json so future loads skip directory scanning."""
        entries = [{"id": item.item_id, "filename": item._path.name} for item in items]
        index_path = self._cache_dir / _INDEX_NAME
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            index_path.write_text(json.dumps(entries))
        except OSError as exc:
            _log.warning("Could not write cache index: %s", exc)
