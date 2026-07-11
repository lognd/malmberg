"""MediaStore: in-memory media index with JSON-lines persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_core.models import MediaItem, MediaPage
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import META_SCHEMA_VERSION, extract_exif

_log = get_logger(__name__)


class MediaStore:
    """Thread-safe (single-process) media index backed by a JSON-lines file.

    All mutations go through this class so that the in-memory dict and the
    on-disk index stay in sync.  The index file is a newline-delimited list of
    MediaItem JSON objects, one per line.  It is rewritten in full on every
    save; for the expected scale (tens of thousands of items) this is fast
    enough and simpler than an append-only log with compaction.
    """

    def __init__(self) -> None:
        self._items: dict[str, MediaItem] = {}
        self._dirty = False
        """Set when a lazy metadata refresh mutates an item in-memory."""

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_from_disk(self, path: Path) -> Result[int, IngestError]:
        """Populate the in-memory index from *path* (JSON-lines).

        Returns Ok(n) with the number of items loaded, or Err if the file
        exists but cannot be parsed.  A missing file is silently treated as
        an empty store.
        """
        if not path.is_file():
            return Ok(0)
        try:
            loaded = 0
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = MediaItem.model_validate_json(line)
                    self._items[item.id] = item
                    loaded += 1
            _log.info("Loaded %d media items from %s", loaded, path)
            return Ok(loaded)
        except Exception as exc:
            _log.error("Failed to load media index from %s: %s", path, exc)
            return Err(IngestError.StorageError)

    def save_to_disk(self, path: Path) -> Result[None, IngestError]:
        """Write the current in-memory index to *path* atomically."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                for item in self._items.values():
                    f.write(item.model_dump_json())
                    f.write("\n")
            tmp.replace(path)
            return Ok(None)
        except Exception as exc:
            _log.error("Failed to save media index to %s: %s", path, exc)
            return Err(IngestError.StorageError)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, item: MediaItem) -> None:
        """Insert *item* into the index."""
        self._items[item.id] = item

    def patch(self, item_id: str, updates: dict) -> Result[MediaItem, IngestError]:
        """Apply *updates* (field-name -> value) to the item with *item_id*."""
        item = self._items.get(item_id)
        if item is None:
            return Err(IngestError.NotFound)
        updated = item.model_copy(update=updates)
        self._items[item_id] = updated
        return Ok(updated)

    def delete(
        self,
        item_id: str,
        trash_root: Path,
        media_root: Path,
    ) -> Result[dict[str, str], IngestError]:
        """Apply hide_policy for *item_id*: trash or tag do_not_display."""
        item = self._items.get(item_id)
        if item is None:
            return Err(IngestError.NotFound)

        if item.hide_policy == "delete":
            src = media_root / item.server_path
            if src.is_file():
                dst = trash_root / item.server_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
            del self._items[item_id]
            _log.info("Trashed %s (%s)", item_id, item.filename)
            return Ok({"status": "trashed", "id": item_id})
        else:
            self._items[item_id] = item.model_copy(update={"do_not_display": True})
            _log.info("Hidden (kept) %s (%s)", item_id, item.filename)
            return Ok({"status": "hidden", "id": item_id})

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(
        self, item_id: str, media_root: Optional[Path] = None
    ) -> Optional[MediaItem]:
        """Return the item with *item_id*, or None if absent.

        If *media_root* is given and the item's metadata schema is stale, it
        is transparently re-extracted before being returned (see
        ``_refresh_if_stale``).
        """
        item = self._items.get(item_id)
        if item is None:
            return None
        if media_root is not None:
            item = self._refresh_if_stale(item, media_root)
        return item

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        skip_hidden: bool = True,
        sort: str = "id",
        media_root: Optional[Path] = None,
    ) -> MediaPage:
        """Return a paginated slice of the media index.

        *sort* controls ordering: ``"id"`` (default, insertion order) or
        ``"recent"`` (newest first, by ``meta.taken_at`` falling back to
        ``meta.ingest_at``). If *media_root* is given, items on the returned
        page with stale metadata are refreshed in place before being served.
        """
        all_items = [
            it for it in self._items.values() if not (skip_hidden and it.do_not_display)
        ]
        if sort == "recent":
            all_items.sort(
                key=lambda it: it.meta.taken_at or it.meta.ingest_at, reverse=True
            )
        total = len(all_items)
        start = (page - 1) * page_size
        chunk = all_items[start : start + page_size]
        if media_root is not None:
            chunk = [self._refresh_if_stale(it, media_root) for it in chunk]
        return MediaPage(
            items=chunk,
            total=total,
            page=page,
            page_size=page_size,
            has_next=(start + page_size) < total,
        )

    def pop_dirty(self) -> bool:
        """Return True if a lazy refresh mutated the index, then clear the flag."""
        was_dirty, self._dirty = self._dirty, False
        return was_dirty

    def _refresh_if_stale(self, item: MediaItem, media_root: Path) -> MediaItem:
        """Re-extract *item*'s metadata if its schema_version is out of date.

        Preserves user-set fields (do_not_display, hide_policy, tags,
        dwell_override_s) and the original ingest_at timestamp. Re-extraction
        failures or a missing source file leave the item unchanged.
        """
        if item.meta.schema_version >= META_SCHEMA_VERSION:
            return item
        path = media_root / item.server_path
        if not path.is_file():
            _log.warning(
                "Cannot refresh stale metadata for %s: file missing at %s",
                item.id,
                path,
            )
            return item
        result = extract_exif(path)
        if result.is_err:
            _log.warning(
                "Metadata refresh failed for %s (%s); keeping stale record",
                item.id,
                result.danger_err,
            )
            return item
        new_meta = result.danger_ok.model_copy(
            update={"ingest_at": item.meta.ingest_at}
        )
        refreshed = item.model_copy(update={"meta": new_meta})
        self._items[item.id] = refreshed
        self._dirty = True
        _log.info(
            "Refreshed metadata for %s (schema %d -> %d)",
            item.id,
            item.meta.schema_version,
            META_SCHEMA_VERSION,
        )
        return refreshed

    def sha256_exists(self, digest: str) -> bool:
        """Return True if any stored item has the given SHA-256 digest."""
        return any(it.meta.sha256 == digest for it in self._items.values())

    def __len__(self) -> int:
        return len(self._items)
