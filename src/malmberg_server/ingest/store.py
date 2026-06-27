"""MediaStore: in-memory media index with JSON-lines persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_core.models import MediaItem, MediaPage
from malmberg_server.ingest.errors import IngestError

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

    def get(self, item_id: str) -> Optional[MediaItem]:
        """Return the item with *item_id*, or None if absent."""
        return self._items.get(item_id)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        skip_hidden: bool = True,
    ) -> MediaPage:
        """Return a paginated slice of the media index."""
        all_items = [
            it for it in self._items.values() if not (skip_hidden and it.do_not_display)
        ]
        total = len(all_items)
        start = (page - 1) * page_size
        chunk = all_items[start : start + page_size]
        return MediaPage(
            items=chunk,
            total=total,
            page=page,
            page_size=page_size,
            has_next=(start + page_size) < total,
        )

    def sha256_exists(self, digest: str) -> bool:
        """Return True if any stored item has the given SHA-256 digest."""
        return any(it.meta.sha256 == digest for it in self._items.values())

    def __len__(self) -> int:
        return len(self._items)
