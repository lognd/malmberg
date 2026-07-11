"""Programmed slideshow (playlist) storage: named ordered lists of item ids.

Persisted as a single JSON file under ``fs_root / "logs" / "playlists.json"``
so playlists survive server restarts. All mutation goes through
``PlaylistStore`` to keep the in-memory dict and on-disk file in sync.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger

_log = get_logger(__name__)


class PlaylistError:
    """Marker namespace for playlist error kinds (see typani.result.Result)."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    STORAGE_ERROR = "storage_error"


class PlaylistStore:
    """In-memory index of named playlists, persisted to a JSON file."""

    def __init__(self) -> None:
        self._playlists: dict[str, list[str]] = {}

    def load_from_disk(self, path: Path) -> Result[int, str]:
        """Populate the in-memory index from *path*.

        A missing file is treated as an empty store. Returns Ok(n) with the
        number of playlists loaded, or Err on parse failure.
        """
        if not path.is_file():
            return Ok(0)
        try:
            data = json.loads(path.read_text())
            self._playlists = {
                str(name): [str(i) for i in items] for name, items in data.items()
            }
            _log.info("Loaded %d playlists from %s", len(self._playlists), path)
            return Ok(len(self._playlists))
        except Exception as exc:
            _log.error("Failed to load playlists from %s: %s", path, exc)
            return Err(PlaylistError.STORAGE_ERROR)

    def save_to_disk(self, path: Path) -> Result[None, str]:
        """Write the current in-memory index to *path* atomically."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._playlists, indent=2, sort_keys=True))
            tmp.replace(path)
            return Ok(None)
        except Exception as exc:
            _log.error("Failed to save playlists to %s: %s", path, exc)
            return Err(PlaylistError.STORAGE_ERROR)

    def list(self) -> list[dict]:
        """Return [{"name": ..., "count": ...}, ...] sorted by name."""
        return [
            {"name": name, "count": len(items)}
            for name, items in sorted(self._playlists.items())
        ]

    def get(self, name: str) -> Optional[list[str]]:
        """Return the ordered item-id list for playlist *name*, or None."""
        return self._playlists.get(name)

    def create(self, name: str) -> Result[None, str]:
        """Create a new empty playlist named *name*."""
        if name in self._playlists:
            return Err(PlaylistError.ALREADY_EXISTS)
        self._playlists[name] = []
        _log.info("Created playlist %r", name)
        return Ok(None)

    def delete(self, name: str) -> Result[None, str]:
        """Delete the playlist named *name*."""
        if name not in self._playlists:
            return Err(PlaylistError.NOT_FOUND)
        del self._playlists[name]
        _log.info("Deleted playlist %r", name)
        return Ok(None)

    def add_item(self, name: str, item_id: str) -> Result[list[str], str]:
        """Append *item_id* to playlist *name* if not already present."""
        items = self._playlists.get(name)
        if items is None:
            return Err(PlaylistError.NOT_FOUND)
        if item_id not in items:
            items.append(item_id)
            _log.info("Added %s to playlist %r", item_id, name)
        return Ok(items)

    def remove_item(self, name: str, item_id: str) -> Result[list[str], str]:
        """Remove *item_id* from playlist *name* if present."""
        items = self._playlists.get(name)
        if items is None:
            return Err(PlaylistError.NOT_FOUND)
        if item_id in items:
            items.remove(item_id)
            _log.info("Removed %s from playlist %r", item_id, name)
        return Ok(items)

    def __len__(self) -> int:
        return len(self._playlists)
