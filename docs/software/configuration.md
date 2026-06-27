# Configuration reference

Both roles read configuration from three sources, merged in this priority order
(highest wins):

1. CLI flags
2. Environment variables prefixed `MALMBERG_`
3. TOML config file
4. Hardcoded defaults

`ServerConfig` and `DisplayConfig` are Pydantic models; invalid values are rejected
at startup with a descriptive error message.

---

## Server configuration

Config file: `~/.config/malmberg/server.toml` (or the path passed to `--config`)

| Field | Type | Default | Env var | Description |
|-------|------|---------|---------|-------------|
| `host` | str | `"0.0.0.0"` | `MALMBERG_HOST` | Bind address for the HTTP server |
| `port` | int | `8444` | `MALMBERG_PORT` | Listen port |
| `fs_root` | path | `/fs` | `MALMBERG_FS_ROOT` | Root of the media filesystem |
| `hide_policy` | `"delete"` \| `"keep"` | `"delete"` | `MALMBERG_HIDE_POLICY` | Default behaviour when a display hides an item |
| `trash_purge_days` | int | `30` | -- | Days before soft-deleted files in `.trash/` are permanently removed |
| `max_upload_mb` | int | `500` | -- | Maximum file size accepted by `POST /upload` |
| `backup_retention` | int | `20` | -- | Number of ZFS snapshots to retain (exponential-backoff policy) |
| `log_retention` | int | `10` | -- | Number of log files to retain (same policy as `backup_retention`) |

The `hide_policy` field controls what `DELETE /media/{id}` does by default. It can
also be overridden per item via `PATCH /media/{id}`. See
[server.md](../design/server.md#54-do-not-display-policy) for details.

The `backup_retention` and `log_retention` counts use a probabilistic exponential-
backoff algorithm: the most recent `n` items are always kept, and older items are
retained with probability that halves with each additional step back. See
[backup.md](../design/backup.md#backup-retention-circular-buffer-with-exponential-backoff).

**Example `server.toml`:**

```toml
host = "0.0.0.0"
port = 8444
fs_root = "/fs"
hide_policy = "keep"
trash_purge_days = 60
max_upload_mb = 1000
backup_retention = 30
```

---

## Display configuration

Config file: `~/.config/malmberg/display.toml` (or the path passed to `--config`)

| Field | Type | Default | Env var | Description |
|-------|------|---------|---------|-------------|
| `host` | str | `"0.0.0.0"` | `MALMBERG_HOST` | Bind address for the display's HTTP API |
| `port` | int | `8443` | `MALMBERG_PORT` | Listen port |
| `cache_dir` | path | `~/.cache/malmberg/display` | -- | Local directory for the offline media cache |
| `dwell_s` | float | `10.0` | `MALMBERG_DWELL_S` | Seconds to show each item before advancing |
| `fade_duration_s` | float | `0.5` | -- | Cross-fade transition duration in seconds |
| `web_overlays` | bool | `false` | `MALMBERG_WEB_OVERLAYS` | Enable playwright-rendered clock and weather overlays |
| `offline_cache_size` | int | `500` | -- | Maximum number of items kept in the offline LRU cache |
| `width` | int | `1920` | -- | Display width in pixels |
| `height` | int | `1080` | -- | Display height in pixels |
| `media_dir` | path \| null | `null` | -- | Use a local directory as the media source instead of a server |
| `server_url` | str \| null | `null` | `MALMBERG_SERVER_URL` | Explicit server base URL (e.g. `http://192.168.1.10:8444`); skips UDP discovery when set |
| `discovery_port` | int | `9456` | -- | UDP port used for automatic server discovery broadcasts |
| `history_len` | int | `32` | -- | Number of recently displayed items to keep for backward navigation |

**Media source priority:** if `media_dir` is set, it is used exclusively (no server
connection). If `server_url` is set, the display connects directly to that URL and
skips UDP discovery. If neither is set, the display listens for UDP broadcasts and
falls back to the offline cache while waiting.

`web_overlays` requires the `[web-overlays]` pip extra and `playwright_supported=true`
in the hardware profile. On hardware that does not support it the flag is ignored.

**Example `display.toml`:**

```toml
dwell_s = 8.0
fade_duration_s = 1.0
width = 1920
height = 1080
server_url = "http://192.168.1.10:8444"
```

---

## Hardware profile

File: `~/.config/malmberg/hardware.toml`

Written by `python -m malmberg_server setup` or `python -m malmberg_display setup`.
Do not edit manually unless you need to override detection results.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Profile name, e.g. `"pi-4"` or `"generic-x86"` |
| `hw_video_decode` | bool | Whether mpv can use hardware-accelerated video decode on this board |
| `gpio_available` | bool | Whether RPi GPIO pins are accessible (physical buttons, status LEDs) |
| `status_panel_bus` | `"i2c"` \| `"spi"` \| `"none"` | Which bus drives the optional e-ink or OLED status panel |
| `max_preload_queue` | int | Depth of the slideshow preload queue, scaled for available RAM |
| `playwright_supported` | bool | Whether there is enough RAM to run a headless Chromium instance |

If `hardware.toml` does not exist, the system falls back to a safe generic-x86
profile with `gpio_available=false`, `status_panel_bus="none"`, `max_preload_queue=4`,
and `playwright_supported=true`. See [architecture.md](../design/architecture.md#35-hardware-abstraction-layer-hal).

**Example `hardware.toml` for a Pi 4:**

```toml
name = "pi-4"
hw_video_decode = true
gpio_available = true
status_panel_bus = "none"
max_preload_queue = 4
playwright_supported = true
```

**Example `hardware.toml` for a Pi Zero 2 W:**

```toml
name = "pi-zero-2w"
hw_video_decode = false
gpio_available = true
status_panel_bus = "none"
max_preload_queue = 2
playwright_supported = false
```
