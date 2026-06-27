# Module reference

This page describes what each module does and what you would import from it. For the
HTTP-level API see [api-reference.md](api-reference.md). For design rationale see
[design/reference.md](../design/reference.md).

---

## `malmberg_core`

Shared primitives used by both the server and the display. Never imports from
`malmberg_server` or `malmberg_display`.

### `malmberg_core.hal`

Hardware Abstraction Layer. The sole source of truth for capability flags.

```python
from malmberg_core.hal import get_hardware_profile, write_hardware_toml
from malmberg_core.hal import HardwareProfile, HalError
```

- `get_hardware_profile(config_path=None) -> HardwareProfile` -- loads
  `hardware.toml` from the default path or an explicit one. Falls back to a safe
  generic-x86 profile if the file does not exist. Returns a `HardwareProfile`
  directly (raises on parse error -- call sites that need error handling should use
  `_load_from_toml` directly).
- `write_hardware_toml(profile, path)` -- serialize a `HardwareProfile` to TOML.
  Used by provisioning scripts.
- `HardwareProfile` -- Pydantic model with fields `name`, `hw_video_decode`,
  `gpio_available`, `status_panel_bus`, `max_preload_queue`, `playwright_supported`.
  See [configuration.md](configuration.md#hardware-profile) for field descriptions.
- `HalError` -- `ErrorSet` with variants `FileNotFound`, `ParseError`,
  `DetectionFailed`.

Application code must never branch on `sys.platform` or `/proc/cpuinfo`. Always
branch on `profile.<capability>`.

### `malmberg_core.logging`

```python
from malmberg_core.logging import get_logger
log = get_logger(__name__)
```

Returns a standard `logging.Logger`. On first call, configures split handlers:
DEBUG and INFO go to stdout; WARNING and above go to stderr. Subsequent calls
return the same logger instance. No `print()` anywhere in library or application
code -- use this instead.

### `malmberg_core.models`

All shared Pydantic models.

```python
from malmberg_core.models import (
    Tag,
    MediaItem,
    MediaMetadata,
    MediaPage,
    DiscoveryPayload,
    HidePolicy,
)
```

- `Tag` -- identity envelope (`name`, `id`, `version`, `mac`); returned by `GET /`
  on both roles.
- `MediaItem` / `MediaMetadata` / `MediaPage` -- media index models; see
  [api-reference.md](api-reference.md#data-models).
- `DiscoveryPayload` -- UDP broadcast body (`role`, `mac`, `port`, optional `pin`).
- `HidePolicy` -- `Literal["delete", "keep"]` type alias.

### `malmberg_core.networking`

```python
from malmberg_core.networking import (
    get_mac_address,
    broadcast_udp,
    listen_udp,
    parse_broadcast,
)
```

- `get_mac_address() -> str` -- returns the primary MAC address as
  `"AA:BB:CC:DD:EE:FF"`.
- `broadcast_udp(payload, port, *, interval_s=5.0, stop_event=None)` -- async
  coroutine; broadcasts `payload` as JSON to `<broadcast>:<port>` every
  `interval_s` seconds until `stop_event` is set.
- `listen_udp(port, handler, *, stop_event=None)` -- async coroutine; binds to
  `0.0.0.0:<port>` and calls `handler(data, addr)` for each datagram received.
- `parse_broadcast(data) -> dict | None` -- decode a UDP datagram as JSON; returns
  `None` on any parse error.

### `malmberg_core.compat`

```python
from malmberg_core.compat import toml, Self, TaskGroup
```

- `toml` -- `tomllib` (3.11+), then `tomli`, then `toml`; always has `.load(fp)`
  and `.loads(s)`.
- `Self` -- re-export from `typing` (3.11+) or `typing_extensions`.
- `TaskGroup` -- `asyncio.TaskGroup` (3.11+) with a minimal 3.10 backport.

### `malmberg_core.version`

```python
from malmberg_core import __version__
```

Resolved from the installed package metadata, then from `pyproject.toml`, then
falls back to `"0.0.0"`.

---

## `malmberg_server`

### `malmberg_server.app.config`

```python
from malmberg_server.app.config import ServerConfig
cfg = ServerConfig.from_external(args, toml_dict)
```

Pydantic model holding all server runtime configuration. `from_external` merges CLI
args, environment variables, and TOML in the correct priority order. Field
descriptions are in [configuration.md](configuration.md#server-configuration).

### `malmberg_server.app.app`

```python
from malmberg_server.app.app import ServerApp
ServerApp(cfg)()  # blocks until process exits
```

Owns the full server lifecycle: ensures directory structure, loads `MediaStore` from
disk, builds the FastAPI app, and starts uvicorn. `__call__` runs the asyncio event
loop and returns `Unreachable`.

### `malmberg_server.api.routes`

```python
from malmberg_server.api.routes import build_app
app = build_app(cfg, store=existing_store)
```

Factory function that creates the FastAPI application. Pass a pre-loaded `MediaStore`
to preserve state across restarts; omit it to start with an empty in-memory store.
Import this directly in tests to avoid starting uvicorn.

### `malmberg_server.ingest`

```python
from malmberg_server.ingest import (
    IngestError,
    MediaStore,
    extract_exif,
    handle_upload,
    sha256_of_file,
)
```

- `IngestError` -- `ErrorSet` with variants: `FileTooLarge`, `IOError`, `ExifError`,
  `DuplicateFile`, `NotFound`, `StorageError`.
- `MediaStore` -- in-memory media index backed by a JSON-lines file.
  - `add(item)` -- insert an item.
  - `get(id) -> MediaItem | None` -- look up by UUID.
  - `patch(id, updates) -> Result[MediaItem, IngestError]` -- apply a dict of
    field updates.
  - `delete(id, trash_root, media_root) -> Result[dict, IngestError]` -- apply
    hide policy.
  - `list(*, page, page_size, skip_hidden) -> MediaPage` -- paginated query.
  - `sha256_exists(digest) -> bool` -- deduplication check.
  - `load_from_disk(path) -> Result[int, IngestError]` -- populate from a
    JSON-lines file; returns `Ok(n)` with the count loaded.
  - `save_to_disk(path) -> Result[None, IngestError]` -- atomic write via `.tmp`
    then rename.
- `extract_exif(path) -> Result[MediaMetadata, IngestError]` -- uses Pillow to read
  `DateTimeOriginal`, GPS coordinates, camera model, and image dimensions. Returns
  minimal metadata for video files (sha256 only, no EXIF parsing).
- `handle_upload(file, store, media_root, upload_root, max_bytes) -> Result[MediaItem, IngestError]`
  -- streams to `upload_root`, computes SHA-256, checks for duplicates, calls
  `extract_exif`, moves to `media_root/YYYY/MM/DD/filename`, calls `store.add`.
- `sha256_of_file(path) -> str` -- returns the hex digest; raises `OSError` on
  missing file.

### `malmberg_server.backup`

```python
from malmberg_server.backup import (
    BackupError,
    compute_deletions,
    AuditLog,
    AuditEntry,
    snapshot,
    list_snapshots,
    delete_snapshot,
)
```

- `BackupError` -- `ErrorSet` with `CommandFailed`, `ParseError`, `NotFound`,
  `IOError`.
- `compute_deletions(snapshots, n_keep) -> list[str]` -- given a list of snapshot
  names (oldest first) and a retention count, returns the names to delete. The most
  recent `n_keep` are always preserved; older entries are subject to probabilistic
  halving. Deterministic per snapshot name (hash-based).
- `AuditLog(path)` -- append-only JSON-lines log.
  - `append(entry) -> Result[None, BackupError]`
  - `read_all() -> Result[list[AuditEntry], BackupError]`
- `AuditEntry` -- Pydantic model: `timestamp`, `action`, `dataset`,
  `snapshot_name`, `detail`. Construct with `AuditEntry.make(action, ...)`.
- `snapshot(dataset) -> Result[str, BackupError]` -- creates
  `<dataset>@malmberg-<utc-ts>`; returns the full snapshot name.
- `list_snapshots(dataset) -> Result[list[str], BackupError]` -- lists snapshots
  belonging to `dataset` only (not child datasets), oldest first.
- `delete_snapshot(name) -> Result[None, BackupError]` -- destroys the snapshot;
  returns `Err(NotFound)` if it does not exist.

All ZFS functions call `zfs`/`zpool` via subprocess. They never raise; they always
return `Result`.

---

## `malmberg_display`

### `malmberg_display.app.config`

```python
from malmberg_display.app.config import DisplayConfig
cfg = DisplayConfig.from_external(args, toml_dict)
```

Pydantic model for display configuration. See
[configuration.md](configuration.md#display-configuration).

### `malmberg_display.app.app`

```python
from malmberg_display.app.app import DisplayApp
DisplayApp(cfg)()
```

Starts the display event loop in a single `asyncio.TaskGroup` containing:
- `slideshow.produce_target()` -- pre-loads items into the queue
- `slideshow.display_target()` -- pops and renders items
- `uvicorn.Server.serve()` -- the display HTTP API
- `_pairing_task()` (discovery mode only) -- listens for UDP server broadcasts and
  hot-swaps the producer when a server is found

### `malmberg_display.api.routes`

```python
from malmberg_display.api.routes import build_app
app = build_app(slideshow)
```

Factory; creates the display FastAPI application wired to a `Slideshow` instance.

### `malmberg_display.display.proto`

```python
from malmberg_display.display.proto import Displayable, LoadContext, DisplayContext
```

- `Displayable` -- abstract base class. Subclasses implement `async load(ctx:
  LoadContext)` (called once, in the producer task) and `async display(ctx:
  DisplayContext)` (called in the display task, blocks for dwell duration).
- `LoadContext` -- holds `cache_dir` (Path) and optionally initialized pygame and
  mpv resources shared across items.
- `DisplayContext` -- holds `screen`, `mpv_player`, `width`, `height`,
  `fade_duration_s`, `dwell_s`.

### `malmberg_display.display.picture`

```python
from malmberg_display.display.picture import PictureDisplay
```

Implements `Displayable` for images. Uses Pillow to decode (in an executor, off the
event loop) and pygame to render with a cross-fade transition. Importing this module
requires `pygame` and `Pillow` to be installed.

### `malmberg_display.display.video`

```python
from malmberg_display.display.video import VideoDisplay
```

Implements `Displayable` for video. Uses python-mpv. Blocks the display task until
the mpv end-of-file event fires. Requires `mpv` to be installed.

### `malmberg_display.display.web`

```python
from malmberg_display.display.web import WebDisplay
```

Implements `Displayable` for web overlays (clock, weather, etc.). Uses playwright
to capture a screenshot and pygame to composite it. Only usable when
`profile.playwright_supported` is true and `cfg.web_overlays` is enabled. Requires
the `[web-overlays]` extra.

### `malmberg_display.slideshow.slideshow`

```python
from malmberg_display.slideshow.slideshow import Slideshow

show = Slideshow(producer, load_ctx, display_ctx, max_preload=4, history_len=32)
```

Owns the produce/display pipeline.

- `produce_target()` -- async coroutine; calls `next()` or `__anext__()` on the
  producer, awaits `item.load()`, enqueues. Handles both sync and async iterators.
- `display_target()` -- async coroutine; dequeues and awaits `item.display()`;
  respects `is_paused`.
- `set_producer(producer)` -- hot-swap the active producer at runtime; takes effect
  on the next produce cycle.
- `pause()` / `resume()` -- toggle the display task.
- `current -> Displayable | None` -- the item currently being displayed.
- `history -> list[Displayable]` -- snapshot of recent history, newest first.
- `queue_depth -> int` -- pre-loaded items waiting in the queue.
- `is_paused -> bool`

### `malmberg_display.slideshow.producers`

```python
from malmberg_display.slideshow.producers import (
    load_infinite,
    async_load_infinite,
    load_flat_from_directory,
    load_recr_from_directory,
    classify_file,
    ServerProducer,
    CacheProducer,
    CachedItem,
)
```

- `classify_file(path) -> "image" | "video" | None` -- classify by extension.
- `load_flat_from_directory(path) -> Generator[Displayable, None, None]` -- yields
  all media in a single directory (non-recursive).
- `load_recr_from_directory(path) -> Generator[Displayable, None, None]` -- yields
  all media found recursively under `path`.
- `load_infinite(factory, *, shuffle=True) -> Generator` -- wraps a sync generator
  factory; on each exhaustion, calls the factory again and optionally shuffles the
  new batch. Loops forever (returns only when the factory yields nothing).
- `async_load_infinite(factory) -> AsyncGenerator` -- same pattern for async
  generator factories (e.g. `ServerProducer.items`).
- `ServerProducer(server_url, cache_dir, http_client)` -- async generator.
  `items()` paginates through `GET /media`, downloads files to
  `cache_dir/<item_id>/<filename>`, and yields `CachedItem` instances. Already-
  cached files are served without re-downloading.
- `CacheProducer(cache_dir)` -- sync generator. `items()` reads `cache-index.json`
  if present; otherwise scans `cache_dir/` for subdirectories. Used in offline
  mode. `write_index(items)` persists an index for fast future loads.
- `CachedItem(path, item_id)` -- `Displayable` wrapping a local file. `load()`
  defers import of `PictureDisplay` or `VideoDisplay` based on file extension
  (avoiding transitive pygame/mpv imports at collection time).

---

## Error handling pattern

All fallible operations that callers must handle return `Result[T, E]` from
`typani`. `danger_ok` and `danger_err` are **properties**, not methods -- do not
call them with parentheses.

```python
from malmberg_server.ingest import MediaStore, IngestError

store = MediaStore()
result = store.patch(item_id, {"do_not_display": True})
if result.is_err:
    log.warning("Patch failed: %s", result.danger_err)
    return
item = result.danger_ok  # property -- no ()
```

Use `Err(SomeError.Variant)` and `Ok(value)` to construct results. Use exceptions
only for genuinely unrecoverable programmer errors.
