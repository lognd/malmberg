# Architecture Decisions

## 3.1 Language and Runtime

- **Python >= 3.11** throughout.
- `asyncio` single-process event loop for both server and display. Two long-lived
  coroutine tasks: `produce_target` (pre-loads next item) and `display_target`
  (pops from queue and renders). FastAPI runs inside the same loop via `uvicorn`.
- Pydantic v2 for all external data (config, API request/response bodies,
  TOML values). Use `typani` for internal error propagation (e.g. `Result`,
  `Unreachable`).

## 3.2 Transport

- **HTTPS everywhere.** Both Server and Display expose a TLS HTTPS API.
  Self-signed certificates are generated at provisioning time; each node pins
  the peer certificate during the handshake (see handshake.md).
- **UDP broadcast** is used only for peer discovery (short, unsigned, low-trust
  datagrams). Actual data never travels over UDP.

## 3.3 Display Rendering

- **Images:** Pillow for decode and EXIF extraction; `pygame` (SDL2) for
  full-screen rendering. `pygame` is initialized once and stored in
  `LoadContext` / `DisplayContext`.
- **Video:** `mpv` via `python-mpv` bindings. `mpv` handles hardware-accelerated
  decode where the HAL reports it available. The asyncio event loop yields
  control to mpv for the duration of the clip, then resumes.
- **Web overlays** (clock, weather widget): a headless Chromium instance driven
  by `playwright-python`, rendered to a surface composited on top of pygame.
  `playwright` is an optional dependency gated by `[web-overlays]` extra and a
  config flag; it is never imported unless both are true. On hardware profiles
  that do not support it (e.g. Zero 2 W with low RAM), the config flag defaults
  to `false` and the overlay falls back to a lightweight pygame-rendered clock.

## 3.4 Storage Layout on Server

```
/fs/                    -- owned by low-privilege user `malmberg`
  media/                -- primary photo/video store
    YYYY/MM/DD/         -- date-partitioned by EXIF DateTimeOriginal or ingest date
  uploads/              -- transient staging area; moved into media/ after validation
  cloud/                -- per-provider download cache
    icloud/<account>/
    googlephotos/<account>/
  .trash/               -- soft-deleted files; purged on a configurable schedule
  logs/                 -- rolling log archive
```

ZFS dataset: `tank/malmberg` with `compression=lz4`, `atime=off`.

## 3.5 Hardware Abstraction Layer (HAL)

All hardware-specific capabilities are declared through a HAL so the same
codebase runs on a Pi Zero 2 W, a Pi 4, a Pi 5, or a generic x86 machine
without conditional branches scattered through application code.

```python
# malmberg_core.hal.proto
class HardwareProfile(BaseModel):
    name: str
    hw_video_decode: bool       # mpv can use HW-accelerated decode
    gpio_available: bool        # RPi GPIO accessible
    status_panel_bus: Literal["i2c", "spi", "none"]
    max_preload_queue: int      # memory-scaled queue depth
    playwright_supported: bool  # enough RAM to run headless Chromium
```

`HardwareProfile` is loaded from `hardware.toml` (written by the provisioning
script). Application code imports only `get_hardware_profile()` and branches on
profile fields -- never on raw platform strings.

When a capability is disabled (e.g. `hw_video_decode=False`), the relevant
subsystem falls back to a software path or is skipped entirely. Features with
no reasonable software fallback degrade gracefully: logged as unavailable at
startup, system continues.

## 3.6 Logging and Observability

`malmberg_core.logging.get_logger(__name__)` is the only way to obtain a
logger. DEBUG/INFO go to stdout; WARNING and above go to stderr. Format and
level are configured in `logging/config.toml`. No print statements in
production code.

**Log rotation and retention** follow the same exponential-backoff policy as
backup snapshots (see backup.md): the first `ceil(n/2)` log files are always
retained; older files are subject to probabilistic deletion. Default `n=10`.

**Log access:** logs are exposed via `GET /logs` (paginated, plain text, newest
first). The same endpoint exists on the Display.

**Structured events:** every state transition emits a structured log entry
(JSON lines) to `logs/events.jsonl`. `GET /logs/events` returns this stream
filtered by time range and event type.

## 3.7 Configuration

Both roles read configuration in this priority order (highest wins):

1. CLI flags (argparse)
2. Environment variables prefixed `MALMBERG_`
3. TOML config file (`~/.config/malmberg/{role}.toml` or path from `--config`)
4. Hardcoded defaults

`ServerConfig` and `DisplayConfig` are Pydantic `BaseModel` subclasses.
`from_external(args, toml)` merges all sources. Fields must use Pydantic
validators; never silently accept invalid values.
