# Display Features

## 6.1 Provisioning Script (`malmberg_display.setup`)

Same pattern as server. Additional steps:

- Detect hardware; write `hardware.toml`.
- Disable screen blanking and DPMS.
- Configure `mpv` appropriately for the detected hardware profile.
- Optionally install `playwright` and Chromium if `playwright_supported=True`
  and the user opts in.
- Write `malmberg-display.service` systemd unit.

## 6.2 Slideshow Engine

`Slideshow` owns two asyncio tasks:

- `produce_target`: calls `next(producer)`, awaits `item.load(load_ctx)`, puts
  into a bounded `asyncio.Queue(maxsize=profile.max_preload_queue)`. If the
  queue is full it yields control, preventing runaway pre-loading.
- `display_target`: pops from queue, awaits `item.display(display_ctx)`.

`DisplayContext` and `LoadContext` are Pydantic models holding shared
initialized resources (pygame surface, mpv instance, etc.). They are
constructed once at startup by `DisplayApp`.

**Producers** (`malmberg_display.slideshow.producers`):

| Producer | Description |
|----------|-------------|
| `DirectoryProducer` | Flat or recursive scan of a local directory |
| `ServerProducer` | Pulls media list from paired Server; downloads on-demand |
| `CacheProducer` | Reads from the local offline cache (used in degraded mode) |
| `InfiniteProducer` | Wraps any producer, loops forever, shuffles on each cycle |
| `ScheduledProducer` | Wraps another producer; yields based on a time schedule |

The active producer is set on `Slideshow.set_producer()`. The UI and API can
swap producers at runtime.

## 6.3 Graceful Degradation (Offline Mode)

When the Server becomes unreachable, the Display switches automatically to
`CacheProducer`, which serves previously downloaded media from a local cache
directory. The transition is logged at WARNING level, emits a structured event,
and is displayed on the status panel with an inverted `OFFLINE MODE` indicator
and the timestamp of last successful contact with the Server.

The offline cache is a bounded LRU store (default: 500 items, configurable).
Items are downloaded to cache proactively by `ServerProducer` during normal
operation; the cache is never populated in offline mode itself.

**The offline cache is never silently mistaken for live data.** Any API
response, status panel state, log entry, and on-screen overlay while in offline
mode explicitly says so.

## 6.4 Display Rendering Details

**Image transitions:** configurable cross-fade duration (default 0.5 s) and
optional pan-and-zoom (Ken Burns effect). Rendered in pygame.

**Per-image dwell time:** default configured in `DisplayConfig`. Can be
overridden per-file via server-side tag.

**EXIF overlay:** optional HUD showing date taken, camera model, and GPS
location (reverse-geocoded via `geopy` with a local Nominatim cache).

**Clock overlay:** renders current time in a corner. Falls back to pygame text
if `playwright_supported=False`.

## 6.5 Physical UI

Button input is read via GPIO (RPi, HAL-gated) or a USB HID device (fallback
on non-GPIO hardware). If neither is available the button subsystem is a no-op.

| Action | Button |
|--------|--------|
| Next item | Single press |
| Previous item (from history) | Double press |
| Toggle EXIF overlay | Long press |
| Pause/resume slideshow | Triple press |
| Hide current item | Hold 3 s (confirms with brief visual flash before acting) |

History is a `deque(maxlen=32)` on `Slideshow`. Navigation into history does
not alter the producer queue.

## 6.6 Display API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Returns `Tag` |
| GET | `/status` | Current item, queue depth, paired server, online/offline mode |
| POST | `/slideshow/next` | Skip to next item |
| POST | `/slideshow/prev` | Jump to previous history item |
| POST | `/slideshow/pause` | Pause/resume |
| POST | `/slideshow/hide` | Hide current item (applies `hide_policy` via Server) |
| PUT | `/config` | Hot-reload display config subset |
| GET | `/history` | Recent display history (file IDs + timestamps) |
| GET | `/logs` | Rolling log tail (paginated, plain text) |
| GET | `/logs/events` | Structured event stream (JSON lines, filterable) |
