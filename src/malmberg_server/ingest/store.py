"""MediaStore: in-memory media index with JSON-lines persistence."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_core.models import MediaItem, MediaPage
from malmberg_server.faces.people import PersonStore
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import META_SCHEMA_VERSION, extract_exif

_log = get_logger(__name__)

ItemList = list[MediaItem]
"""Spelled out here, at module scope, because inside MediaStore the name ``list``
is the paging method, not the builtin."""

_VIEW_CACHE_SIZE = 8
"""Distinct filter sets to keep pre-filtered views for. Enough that flipping
between a few years/places in the tree stays warm; small enough that the cached
lists (references only) stay a rounding error against the library itself."""

UNSORTED = "unsorted"
"""Sentinel value for the ``q_time`` / ``q_place`` filters meaning "the field
is empty": items with no effective date, or no effective place. Lets the
dashboard surface the screenshots and other undated/unlocated junk that would
otherwise be invisible in the by-year and by-place breakdowns."""


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
        self._digests: dict[str, int] = {}
        """SHA-256 -> how many items carry it. Upload dedup asks this question
        once per incoming file; answering it by scanning every item made a bulk
        import quadratic in the size of the library."""
        self._version = 0
        """Bumped on every mutation. The derived aggregates below are rebuilt
        only when it moves, which is what stops /stats and the /places
        autocomplete (a request per keystroke) from re-walking 20k items each
        time."""
        self._stats_cache: dict[tuple, dict] = {}
        self._counts_cache: dict[tuple, dict[str, int]] = {}
        self._view_cache: OrderedDict[tuple, ItemList] = OrderedDict()
        """Filtered+sorted item lists, keyed by (version, filters). Paging is a
        slice of one of these: without it, every page turn (and the dashboard's
        prefetch of the next page, so twice per turn) re-filtered and re-sorted
        the whole library."""

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
                    self._put(item)
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
    #
    # Every write goes through _put/_drop. That is the whole contract that
    # keeps the derived indexes (digests, cached aggregates) honest: assigning
    # into self._items directly anywhere else would silently desync them.
    # ------------------------------------------------------------------

    def _put(self, item: MediaItem) -> None:
        """Insert or replace *item*, keeping the derived indexes in step."""
        old = self._items.get(item.id)
        if old is not None and old.meta.sha256:
            n = self._digests.get(old.meta.sha256, 0) - 1
            if n > 0:
                self._digests[old.meta.sha256] = n
            else:
                self._digests.pop(old.meta.sha256, None)
        if item.meta.sha256:
            self._digests[item.meta.sha256] = self._digests.get(item.meta.sha256, 0) + 1
        self._items[item.id] = item
        self._version += 1

    def _drop(self, item_id: str) -> None:
        """Remove *item_id*, keeping the derived indexes in step."""
        item = self._items.pop(item_id, None)
        if item is None:
            return
        if item.meta.sha256:
            n = self._digests.get(item.meta.sha256, 0) - 1
            if n > 0:
                self._digests[item.meta.sha256] = n
            else:
                self._digests.pop(item.meta.sha256, None)
        self._version += 1

    def add(self, item: MediaItem) -> None:
        """Insert *item* into the index."""
        self._put(item)

    def patch(self, item_id: str, updates: dict) -> Result[MediaItem, IngestError]:
        """Apply *updates* (field-name -> value) to the item with *item_id*."""
        item = self._items.get(item_id)
        if item is None:
            return Err(IngestError.NotFound)
        updated = item.model_copy(update=updates)
        self._put(updated)
        return Ok(updated)

    def delete(
        self,
        item_id: str,
        trash_root: Path,
        media_root: Path,
    ) -> Result[dict[str, str], IngestError]:
        """Apply hide_policy for *item_id*: recoverable trash, or tag do_not_display."""
        item = self._items.get(item_id)
        if item is None:
            return Err(IngestError.NotFound)

        if item.hide_policy == "delete":
            src = media_root / item.server_path
            if src.is_file():
                dst = trash_root / item.server_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
            # Keep the index entry (marked trashed) so the item remains
            # listable in the recycle bin and restorable; only the normal
            # list()/stats() views and producers exclude it.
            self._put(
                item.model_copy(
                    update={
                        "trashed_at": datetime.now(timezone.utc),
                        "trash_path": item.server_path,
                    }
                )
            )
            _log.info("Trashed %s (%s)", item_id, item.filename)
            return Ok({"status": "trashed", "id": item_id})
        else:
            self._put(item.model_copy(update={"do_not_display": True}))
            _log.info("Hidden (kept) %s (%s)", item_id, item.filename)
            return Ok({"status": "hidden", "id": item_id})

    def delete_permanent(
        self,
        item_id: str,
        media_root: Path,
        trash_root: Optional[Path] = None,
    ) -> Result[dict[str, str], IngestError]:
        """Permanently remove *item_id*: drop the index entry and unlink the file.

        Looks for the file under *trash_root* when the item is currently
        trashed (its ``trash_path`` is set) and *trash_root* is given,
        otherwise under *media_root*. Unlike ``delete``, this is never
        recoverable. Missing files on disk are ignored (index entry is still
        removed).
        """
        item = self._items.get(item_id)
        if item is None:
            return Err(IngestError.NotFound)
        if item.trashed_at is not None and trash_root is not None:
            src = trash_root / (item.trash_path or item.server_path)
        else:
            src = media_root / item.server_path
        src.unlink(missing_ok=True)
        self._drop(item_id)
        _log.info("Permanently deleted %s (%s)", item_id, item.filename)
        return Ok({"status": "deleted", "id": item_id})

    def restore(
        self,
        item_id: str,
        trash_root: Path,
        media_root: Path,
    ) -> Result[MediaItem, IngestError]:
        """Un-trash *item_id*: move its file back from *trash_root* and clear the flag.

        Returns NotFound if the item is unknown, and StorageError if it is
        known but not currently trashed, or if the file is missing from
        trash.
        """
        item = self._items.get(item_id)
        if item is None:
            return Err(IngestError.NotFound)
        if item.trashed_at is None:
            return Err(IngestError.StorageError)
        src = trash_root / (item.trash_path or item.server_path)
        dst = media_root / item.server_path
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        elif not dst.is_file():
            _log.error("Cannot restore %s: file missing from trash and media", item_id)
            return Err(IngestError.StorageError)
        restored = item.model_copy(update={"trashed_at": None, "trash_path": None})
        self._put(restored)
        _log.info("Restored %s (%s) from trash", item_id, item.filename)
        return Ok(restored)

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
        q: Optional[str] = None,
        q_time: Optional[str] = None,
        q_place: Optional[str] = None,
        q_person: Optional[str] = None,
        people: Optional["PersonStore"] = None,
    ) -> MediaPage:
        """Return a paginated slice of the media index.

        *sort* controls ordering: ``"id"`` (default, insertion order) or
        ``"recent"`` (newest first, by ``meta.taken_at`` falling back to
        ``meta.ingest_at``). If *media_root* is given, items on the returned
        page with stale metadata are refreshed in place before being served.
        *q*, if given, filters to items whose filename contains *q*
        (case-insensitive), whose ``meta.taken_at`` year equals *q* when *q*
        is a 4-digit year, whose ``meta.place`` contains *q*
        (case-insensitive), or (when *people* is given) whose detected
        person(s) have a name containing *q*. *q_time*, *q_place*,
        *q_person*, if given, are combined with *q* and each other by AND:
        an item must match every provided filter. *q_time* matches a
        4-digit year or ``YYYY-MM`` against ``meta.taken_at``; *q_place* is
        a case-insensitive substring of ``meta.place``; *q_person* matches a
        person name (via *people*) present on the item. *q_time* or *q_place*
        set to ``UNSORTED`` instead selects the items missing that field
        entirely.
        """
        all_items = self._view(
            skip_hidden=skip_hidden,
            sort=sort,
            q=q,
            q_time=q_time,
            q_place=q_place,
            q_person=q_person,
            people=people,
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

    def _view(
        self,
        *,
        skip_hidden: bool,
        sort: str,
        q: Optional[str],
        q_time: Optional[str],
        q_place: Optional[str],
        q_person: Optional[str],
        people: Optional["PersonStore"],
    ) -> ItemList:
        """The filtered, sorted item list behind one page of ``list``.

        Cached against the mutation counter (plus, when the query touches
        people, their names -- those live in PersonStore and change without
        touching this store, so a rename must invalidate the view too). The
        list is owned by the cache: callers may slice it, never mutate it.
        """
        people_fp = (
            people.name_fingerprint() if people is not None and (q or q_person) else 0
        )
        key = (
            self._version,
            skip_hidden,
            sort,
            q or "",
            q_time or "",
            q_place or "",
            q_person or "",
            people_fp,
        )
        cached = self._view_cache.get(key)
        if cached is not None:
            self._view_cache.move_to_end(key)
            return cached

        items = [
            it
            for it in self._items.values()
            if it.trashed_at is None and not (skip_hidden and it.do_not_display)
        ]
        if q:
            items = [it for it in items if self._matches_query(it, q, people=people)]
        if q_time or q_place or q_person:
            items = [
                it
                for it in items
                if self._matches_filters(
                    it,
                    q_time=q_time,
                    q_place=q_place,
                    q_person=q_person,
                    people=people,
                )
            ]
        if sort == "recent":
            items.sort(
                key=lambda it: it.meta.effective_taken_at or it.meta.ingest_at,
                reverse=True,
            )

        # Entries for older versions can never be hit again, so drop them all
        # rather than letting them age out one eviction at a time.
        stale = [k for k in self._view_cache if k[0] != self._version]
        for k in stale:
            del self._view_cache[k]
        self._view_cache[key] = items
        while len(self._view_cache) > _VIEW_CACHE_SIZE:
            self._view_cache.popitem(last=False)
        return items

    def list_trash(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> MediaPage:
        """Return a paginated slice of trashed items only (the recycle bin)."""
        all_items = [it for it in self._items.values() if it.trashed_at is not None]
        all_items.sort(key=lambda it: it.trashed_at, reverse=True)
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

    def pop_dirty(self) -> bool:
        """Return True if a lazy refresh mutated the index, then clear the flag."""
        was_dirty, self._dirty = self._dirty, False
        return was_dirty

    def _refresh_if_stale(self, item: MediaItem, media_root: Path) -> MediaItem:
        """Re-extract *item*'s metadata if its schema_version is out of date.

        Preserves user-set fields (do_not_display, hide_policy, tags,
        dwell_override_s), the original ingest_at timestamp, and the manual
        date/location overrides (manual_taken_at, manual_lat, manual_lon,
        manual_place) -- these live only in the index, never in the file, so
        a naive re-extract would silently wipe any manually-tagged photo.
        Re-extraction failures or a missing source file leave the item
        unchanged.
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
            update={
                "ingest_at": item.meta.ingest_at,
                "manual_taken_at": item.meta.manual_taken_at,
                "manual_lat": item.meta.manual_lat,
                "manual_lon": item.meta.manual_lon,
                "manual_place": item.meta.manual_place,
            }
        )
        refreshed = item.model_copy(update={"meta": new_meta})
        self._put(refreshed)
        self._dirty = True
        _log.info(
            "Refreshed metadata for %s (schema %d -> %d)",
            item.id,
            item.meta.schema_version,
            META_SCHEMA_VERSION,
        )
        return refreshed

    def sha256_exists(self, digest: str) -> bool:
        """Return True if any stored item has the given SHA-256 digest.

        A dict lookup, not a scan: this is asked once per uploaded file, so a
        scan made importing N files into a library of M cost O(N*M) -- the
        30-minute bulk imports were mostly this.
        """
        return digest in self._digests

    def all_ids(self) -> list[str]:
        """Return every item id currently in the index (trashed included)."""
        return list(self._items.keys())

    def pending_face_ids(self, face_version: int, limit: int) -> list[str]:
        """Return up to *limit* item ids needing (re)processing by the face worker.

        An item is pending if it was never processed, or was processed by a
        face pipeline older than *face_version* (the reprocess / self-heal
        path). Excludes trashed items. Lets the worker walk the library
        without reaching into private state.
        """
        return [
            it.id
            for it in self._items.values()
            if it.trashed_at is None
            and (not it.faces_processed or it.faces_version < face_version)
        ][:limit]

    def counts_by_person(self, *, skip_hidden: bool = True) -> dict[str, int]:
        """Return person_id -> distinct-photo count, for the /people listing.

        Cached against the mutation counter: /people is hit on every dashboard
        load and after every face override, and this walked the whole library
        each time.
        """
        key = (self._version, skip_hidden)
        cached = self._counts_cache.get(key)
        if cached is not None:
            return cached
        counts: dict[str, int] = {}
        for it in self._items.values():
            if it.trashed_at is not None or (skip_hidden and it.do_not_display):
                continue
            for pid in it.person_ids:
                counts[pid] = counts.get(pid, 0) + 1
        self._counts_cache = {key: counts}
        return counts

    def stats(
        self, *, skip_hidden: bool = True, people: Optional["PersonStore"] = None
    ) -> dict:
        """Summarize the library: counts by kind, taken_at date range, by-year.

        Returns a dict with keys ``total``, ``images``, ``videos``,
        ``undated`` (items with no ``meta.taken_at``), ``unplaced`` (items
        with no ``meta.place``; both are the counts behind the ``unsorted``
        q_time / q_place filters), ``earliest``,
        ``latest`` (ISO-8601 strings or None), ``by_year`` (a dict of
        4-digit year string -> count) and ``by_month`` (a dict of
        ``YYYY-MM`` string -> count), both for dated items only, and
        ``by_place`` (a dict of place label -> count, for items with a
        ``meta.place``, sorted by count descending), and, when *people* is
        given, ``by_person`` (a dict of named-person display name -> photo
        count, sorted by count descending; unnamed persons are omitted).
        """
        result = dict(self._base_stats(skip_hidden=skip_hidden))
        if people is not None:
            # Deliberately NOT cached with the rest: names live in PersonStore,
            # which changes without touching this store, so a rename must show
            # up immediately. Built from the cached per-id counts, so it costs
            # one pass over the people, not over the library.
            by_person: dict[str, int] = {}
            for pid, count in self.counts_by_person(skip_hidden=skip_hidden).items():
                person = people.get(pid)
                if person is None or not person.name:
                    continue
                by_person[person.name] = by_person.get(person.name, 0) + count
            result["by_person"] = dict(
                sorted(by_person.items(), key=lambda kv: (-kv[1], kv[0]))
            )
        return result

    def _base_stats(self, *, skip_hidden: bool = True) -> dict:
        """The library-derived half of stats(), cached against _version.

        /stats is polled by the dashboard and /places (autocomplete, a request
        per keystroke) is built straight off it, so this used to re-walk every
        item several times per keystroke.
        """
        key = (self._version, skip_hidden)
        cached = self._stats_cache.get(key)
        if cached is not None:
            return cached
        items = [
            it
            for it in self._items.values()
            if it.trashed_at is None and not (skip_hidden and it.do_not_display)
        ]
        images = sum(1 for it in items if it.kind == "image")
        videos = sum(1 for it in items if it.kind == "video")
        dated = [
            it.meta.effective_taken_at
            for it in items
            if it.meta.effective_taken_at is not None
        ]
        undated = len(items) - len(dated)
        by_year: dict[str, int] = {}
        by_month: dict[str, int] = {}
        for dt in dated:
            year = str(dt.year)
            by_year[year] = by_year.get(year, 0) + 1
            month = f"{dt.year:04d}-{dt.month:02d}"
            by_month[month] = by_month.get(month, 0) + 1
        by_place: dict[str, int] = {}
        unplaced = 0
        for it in items:
            if it.meta.effective_place:
                by_place[it.meta.effective_place] = (
                    by_place.get(it.meta.effective_place, 0) + 1
                )
            else:
                unplaced += 1
        result = {
            "total": len(items),
            "images": images,
            "videos": videos,
            "undated": undated,
            "unplaced": unplaced,
            "earliest": min(dated).isoformat() if dated else None,
            "latest": max(dated).isoformat() if dated else None,
            "by_year": dict(sorted(by_year.items())),
            "by_month": dict(sorted(by_month.items())),
            "by_place": dict(sorted(by_place.items(), key=lambda kv: (-kv[1], kv[0]))),
        }
        # One entry, not a growing map: only the current version is ever a hit,
        # so this is a cache, not a leak.
        self._stats_cache = {key: result}
        return result

    def places(
        self, *, q: str = "", limit: int = 10, skip_hidden: bool = True
    ) -> list[str]:
        """Return distinct place labels whose text contains *q* (case-insensitive),
        most-common first, capped at *limit*. Used for search autocomplete.
        """
        counts = self._base_stats(skip_hidden=skip_hidden)["by_place"]
        needle = q.strip().lower()
        matches = [name for name in counts if needle in name.lower()]
        # counts is already sorted by count desc, name asc; preserve that order.
        return matches[:limit]

    @staticmethod
    def _matches_query(
        item: MediaItem, q: str, *, people: Optional["PersonStore"] = None
    ) -> bool:
        """Return True if *item* matches search query *q*.

        Matches on filename substring, a 4-digit ``meta.taken_at`` year, a
        ``YYYY-MM`` ``meta.taken_at`` year+month, ``meta.place`` substring,
        or (when *people* is given) the name of a person detected in this
        item.
        """
        needle = q.strip().lower()
        if needle in item.filename.lower():
            return True
        taken_at = item.meta.effective_taken_at
        if (
            len(needle) == 4
            and needle.isdigit()
            and taken_at is not None
            and str(taken_at.year) == needle
        ):
            return True
        if (
            len(needle) == 7
            and needle[4] == "-"
            and needle[:4].isdigit()
            and needle[5:].isdigit()
            and taken_at is not None
        ):
            ym = f"{taken_at.year:04d}-{taken_at.month:02d}"
            if ym == needle:
                return True
        place = item.meta.effective_place
        if place is not None and needle in place.lower():
            return True
        if people is not None and item.person_ids:
            for pid in item.person_ids:
                person = people.get(pid)
                if person is not None and person.name and needle in person.name.lower():
                    return True
        return False

    @staticmethod
    def _matches_time(item: MediaItem, q_time: str) -> bool:
        """Return True if ``meta.effective_taken_at`` matches a 4-digit year
        or ``YYYY-MM``, or is absent when *q_time* is ``UNSORTED``."""
        needle = q_time.strip().lower()
        taken_at = item.meta.effective_taken_at
        if needle == UNSORTED:
            return taken_at is None
        if taken_at is None:
            return False
        if len(needle) == 4 and needle.isdigit():
            return str(taken_at.year) == needle
        if (
            len(needle) == 7
            and needle[4] == "-"
            and needle[:4].isdigit()
            and needle[5:].isdigit()
        ):
            ym = f"{taken_at.year:04d}-{taken_at.month:02d}"
            return ym == needle
        return False

    @staticmethod
    def _matches_filters(
        item: MediaItem,
        *,
        q_time: Optional[str] = None,
        q_place: Optional[str] = None,
        q_person: Optional[str] = None,
        people: Optional["PersonStore"] = None,
    ) -> bool:
        """Return True if *item* satisfies EVERY provided filter (AND).

        Each of *q_time*, *q_place*, *q_person* that is non-empty must match
        independently; unspecified filters are ignored. See ``list`` for the
        per-field matching rules.
        """
        if q_time and not MediaStore._matches_time(item, q_time):
            return False
        if q_place:
            needle = q_place.strip().lower()
            place = item.meta.effective_place
            if needle == UNSORTED:
                if place is not None:
                    return False
            elif place is None or needle not in place.lower():
                return False
        if q_person:
            needle = q_person.strip().lower()
            matched = False
            if people is not None:
                for pid in item.person_ids:
                    person = people.get(pid)
                    name = person.name.lower() if person and person.name else ""
                    if name and needle in name:
                        matched = True
                        break
            if not matched:
                return False
        return True

    def __len__(self) -> int:
        return len(self._items)
