# HTTP API reference

Both the server and display expose a FastAPI application over HTTP. In development
both run over plain HTTP. In production they use mutual TLS with pinned certificates
exchanged during the pairing handshake -- see [handshake.md](../design/handshake.md).

---

## Server API

Default port: **8444**

### `GET /`

Returns an identity envelope for the server node.

**Response: `Tag`**

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Human-readable name, always `"Malmberg File Server"` |
| `id` | str | Always `"server"` |
| `version` | str | Package version (e.g. `"0.1.0"`) |
| `mac` | str | Primary MAC address in `AA:BB:CC:DD:EE:FF` format |

```json
{
  "name": "Malmberg File Server",
  "id": "server",
  "version": "0.1.0",
  "mac": "DC:A6:32:01:02:03"
}
```

---

### `GET /status`

Returns runtime health information for the server.

**Response: `ServerStatus`**

| Field | Type | Description |
|-------|------|-------------|
| `version` | str | Package version |
| `uptime_s` | float | Seconds since the server process started |
| `disk_used_bytes` | int | Bytes used on the `fs_root` filesystem |
| `disk_total_bytes` | int | Total bytes on the `fs_root` filesystem |
| `paired_displays` | int | Number of currently paired displays (0 until pairing is implemented) |
| `mode` | str | Always `"running"` while the process is healthy |

```json
{
  "version": "0.1.0",
  "uptime_s": 3721.4,
  "disk_used_bytes": 42949672960,
  "disk_total_bytes": 1099511627776,
  "paired_displays": 0,
  "mode": "running"
}
```

---

### `GET /version`

Returns build and runtime version details -- useful for confirming which commit a
remotely-updated server is actually running. Every field is best-effort: values
that cannot be determined in the current environment (no git checkout, ZFS absent)
are `null` rather than an error.

**Response: `VersionInfo`**

| Field | Type | Description |
|-------|------|-------------|
| `malmberg_version` | str | Installed package version |
| `git_commit` | str \| null | Full commit SHA of the deploy checkout |
| `git_commit_short` | str \| null | First 12 chars of the commit SHA |
| `git_branch` | str \| null | Checked-out branch |
| `git_dirty` | bool \| null | True if the checkout has uncommitted changes |
| `python_version` | str | Running Python interpreter version |
| `platform` | str | OS/kernel/arch string |
| `hardware_profile` | str | Active HAL profile name (e.g. `generic-x86`) |
| `openzfs_version` | str \| null | Loaded OpenZFS kernel-module version |
| `packages` | object | Versions of key dependencies (fastapi, uvicorn, pydantic, pillow) |

```json
{
  "malmberg_version": "0.1.0",
  "git_commit": "4ed41c01dd8acf11f6f5790a36a6ba85dde9d9ed",
  "git_commit_short": "4ed41c01dd8a",
  "git_branch": "main",
  "git_dirty": false,
  "python_version": "3.12.12",
  "platform": "Linux-7.0.0-14-generic-x86_64-with-glibc2.41",
  "hardware_profile": "generic-x86",
  "openzfs_version": "2.4.1-1ubuntu5",
  "packages": {"fastapi": "0.138.1", "uvicorn": "0.49.0", "pydantic": "2.13.4", "pillow": "12.2.0"}
}
```

---

### `GET /media`

Returns a paginated list of media items. Hidden items (`do_not_display=true`) are
excluded.

Items on the returned page whose `meta.schema_version` is behind the server's
current `META_SCHEMA_VERSION` are transparently re-extracted from the source
file before being served (see "Lazy metadata refresh" below), so a metadata
schema change never requires a manual re-ingest of existing files.

**Query parameters**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `page` | int | `1` | >= 1 | Page number (1-based) |
| `page_size` | int | `50` | 1--500 | Items per page |
| `sort` | str | `"id"` | `"id"` \| `"recent"` | `"recent"` orders newest first by `meta.taken_at`, falling back to `meta.ingest_at` |
| `q` | str | none | -- | Filters to items whose `filename` contains *q* (case-insensitive), whose `meta.taken_at` year equals *q* when *q* is a 4-digit year, or whose `meta.place` contains *q* (case-insensitive) |

**Response: `MediaPage`**

| Field | Type | Description |
|-------|------|-------------|
| `items` | list[MediaItem] | Items on this page |
| `total` | int | Total number of visible items |
| `page` | int | Current page number |
| `page_size` | int | Items per page as requested |
| `has_next` | bool | Whether there is a subsequent page |

---

### `GET /media/{id}`

Stream the raw file for a media item.

**Path parameters:** `id` -- the UUID of the media item.

**Response:** binary file content with the appropriate `Content-Type` header.

Like `GET /media`, this transparently refreshes stale metadata for the
requested item before serving the file (metadata refresh does not affect the
byte stream returned).

**Errors:**
- `404` -- item not found in the index, or the file is missing from disk

---

### `GET /places`

Autocomplete: distinct `meta.place` labels containing a prefix/substring,
most-common first. Backs the dashboard's location search-as-you-type
suggestions.

**Query parameters**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `q` | str | `""` | -- | Case-insensitive substring filter |
| `limit` | int | `10` | 1--50 | Maximum number of suggestions returned |

**Response:** `list[str]` -- place labels, e.g. `["Tampa, Florida, US"]`.

---

### `GET /upload`

Serves a self-contained, mobile-first HTML page for bulk-uploading photos and
videos. The page lets an operator pick or drag-and-drop many files at once;
each file is sent as its own `POST /upload` request from the page's inline
JavaScript, with a per-file progress bar and a clear success / "already
exists" (409) / error state, plus an overall summary. No external
CDNs/fonts/scripts are loaded -- the page works even when the server box is
offline. (This is a distinct route from `POST /upload` below.)

**Response:** `text/html`

---

### `GET /dashboard`

Serves a self-contained HTML control dashboard: a responsive grid of the most
recent photos (via `GET /media?sort=recent`, thumbnails via `GET /media/{id}`)
plus Previous / Next / Pause-Resume slideshow controls and a "now playing"
readout. The controls call the `/control/*` endpoints below rather than the
display directly, so the page stays same-origin with the server (no CORS)
even when opened from a phone.

If `ServerConfig.display_url` is not configured, the controls render disabled
with a short hint to set `MALMBERG_DISPLAY_URL`.

**This is also the same page the Display serves at its own `GET /dashboard`**
(see "Display-hosted dashboard" below) -- both are rendered from a single
template, `malmberg_server.api.web.render_dashboard_html(role)`, so the two
accessors never desync. Only a JS `MALMBERG_ROLE` constant differs between
the two: it switches whether slideshow controls target this server's
`/control/*` proxy or the display's own `/slideshow/*` routes directly, and
hides server-only sections (multi-display selection, the year "play query"
shortcut, and programmed slideshows) when hosted on a display.

The page also has a **Recycle bin** panel (see `GET /media/trash` /
`POST /media/{id}/restore` below) and, in the "Control the photo frame"
panel, de-emphasized **Restart display** / **Restart server** buttons behind
a confirmation dialog (see `POST /control/restart` and `POST /admin/restart`
below).

**Response:** `text/html`

---

### `POST /upload`

Ingest a new media file.

**Request:** `multipart/form-data` with a single field named `file` containing the
media file. The filename must be present in the part headers.

**Response: `MediaItem`** (see model below) on success.

**Errors:**

| Status | Cause |
|--------|-------|
| `400` | No filename provided in the multipart part |
| `409` | A file with the same SHA-256 digest already exists (deduplication) |
| `413` | File exceeds `max_upload_mb` (default 500 MB) |
| `422` | File could not be decoded as an image or video |
| `500` | I/O error while writing, or the media index could not be persisted |

The server streams the upload to a staging directory, computes the SHA-256 digest,
checks for duplicates, runs EXIF extraction, then moves the file atomically to
`/fs/media/YYYY/MM/DD/<filename>`.

---

### `PATCH /media/{id}`

Update metadata on an existing media item.

**Request body: `MediaPatch`** -- all fields are optional; omitted fields are not
changed.

| Field | Type | Description |
|-------|------|-------------|
| `do_not_display` | bool \| null | If true, item is hidden from `GET /media` and not served to displays |
| `hide_policy` | `"delete"` \| `"keep"` \| null | Override the item's hide policy |
| `dwell_override_s` | float \| null | Per-item dwell time in seconds; null resets to the global default |
| `tags` | list[str] \| null | Replace the full tag list |

**Response:** the updated `MediaItem`.

**Errors:**
- `404` -- item not found

---

### `DELETE /media/{id}`

Apply the hide policy for a media item (`?permanent=true` bypasses the hide
policy and always hard-deletes).

The action taken depends on the item's `hide_policy` field (which can be set via
`PATCH` before calling `DELETE`):

| `hide_policy` | Action |
|---------------|--------|
| `"delete"` (default) | File is moved to `/fs/.trash/`; item is **marked trashed but kept in the index** (recoverable -- see `GET /media/trash` / `POST /media/{id}/restore`) |
| `"keep"` | Item is tagged `do_not_display=true`; file stays in `/fs/media/` |

Passing `?permanent=true` always hard-deletes: the file is unlinked (from
`/fs/media/` or `/fs/.trash/`, whichever it currently lives under) and the
index entry is dropped. This is never recoverable.

**Response:**

```json
{ "status": "trashed", "id": "..." }
```
or
```json
{ "status": "hidden", "id": "..." }
```
or (when `permanent=true`)
```json
{ "status": "deleted", "id": "..." }
```

**Errors:**
- `404` -- item not found

---

### `GET /media/trash`

List trashed (soft-deleted) items for the recycle bin view -- the same
`MediaPage` shape as `GET /media`, newest-trashed first. Registered ahead of
`GET /media/{id}` in the route table so the literal `trash` path segment is
never swallowed as an item id.

**Query parameters:** `page` (default 1), `page_size` (default 50, max 500).

**Response: `MediaPage`** (see model below), containing only items with
`trashed_at` set.

---

### `POST /media/{id}/restore`

Restore a trashed item: moves its file back from `/fs/.trash/` to
`/fs/media/` and clears `trashed_at` / `trash_path`. The item then
reappears in `GET /media` and disappears from `GET /media/trash`.

**Response:** the restored `MediaItem`.

**Errors:**
- `404` -- item not found
- `500` -- item is known but not currently trashed, or its file is missing
  from both `/fs/.trash/` and `/fs/media/`

---

### `POST /admin/restart`

Acknowledges with `{"status": "restarting"}`, then re-execs this server
process (`os.execv(sys.executable, [sys.executable, "-m", "malmberg_server"]`)
a fraction of a second later so the response has time to flush to the
client. Re-exec (rather than `os.kill`/`sys.exit`) is used deliberately so
this works whether or not a supervisor like systemd is watching the
process. Use when the server needs a remote nudge (e.g. a wedged state) and
nobody is physically at the machine.

**Response:**
```json
{ "status": "restarting" }
```

---

### `POST /control/next`, `POST /control/prev`, `POST /control/pause`, `GET /control/status`, `POST /control/play-all`, `POST /control/show/{id}`, `POST /control/restart`

Proxy endpoints that forward to the paired display's control API
(`{display_url}/slideshow/next`, `/slideshow/prev`, `/slideshow/pause`,
`/status`, `/slideshow/all`, `/slideshow/show/{id}`, `/admin/restart`
respectively). These exist so that browser clients (e.g. the dashboard
page) can control the display same-origin through the server, avoiding
CORS and keeping the display's control API off the open network.

`display_url` is configured via `ServerConfig.display_url` (env
`MALMBERG_DISPLAY_URL`, toml key `display_url`), e.g.
`http://10.0.0.5:8443`.

**Response:** the JSON body returned by the corresponding display endpoint,
passed through unchanged.

**Errors:**

| Status | Cause |
|--------|-------|
| `503` | No `display_url` configured on the server |
| `502` | The display could not be reached, or returned an error |

---

## Data models

### `MediaItem`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | str | (UUID v4) | Unique identifier |
| `kind` | `"image"` \| `"video"` | required | File type |
| `filename` | str | required | Original filename |
| `server_path` | str | required | Relative path from `/fs/media/`, e.g. `"2024/06/15/IMG_0001.jpg"` |
| `meta` | MediaMetadata | (see below) | EXIF and ingest metadata |
| `do_not_display` | bool | `false` | When true, excluded from `GET /media` and not served to displays |
| `hide_policy` | `"delete"` \| `"keep"` | `"delete"` | Behaviour applied by `DELETE /media/{id}` |
| `dwell_override_s` | float \| null | `null` | Per-item display duration; null means use the display's global `dwell_s` |
| `tags` | list[str] | `[]` | Arbitrary user-defined tags |
| `trashed_at` | datetime \| null | `null` | Set by `DELETE /media/{id}` (soft-delete path) when the item is moved to `/fs/.trash/`; cleared by `POST /media/{id}/restore`. Trashed items stay in the index (recoverable, listed by `GET /media/trash`) but are excluded from `GET /media`, `GET /stats`, and every display producer. |
| `trash_path` | str \| null | `null` | Relative path under `/fs/.trash/` where a trashed item's file currently lives; `null` when not trashed. New fields default to `null` so index lines written before this field existed still parse unchanged. |

### `MediaMetadata`

| Field | Type | Description |
|-------|------|-------------|
| `taken_at` | ISO 8601 datetime \| null | `DateTimeOriginal` from EXIF; null if absent or not an image |
| `ingest_at` | ISO 8601 datetime | When the file was received by the server (always set) |
| `camera_model` | str \| null | Camera make and model from EXIF |
| `lat` | float \| null | GPS latitude in decimal degrees (positive = north) |
| `lon` | float \| null | GPS longitude in decimal degrees (positive = east) |
| `place` | str \| null | Human-readable place label reverse-geocoded from `lat`/`lon` offline on the server, e.g. `"Tampa, Florida, US"` (city, region, country code); null when there is no GPS fix or the `geocode` extra is not installed. Never populated via an online lookup -- see "Reverse geocoding (place names)" below. |
| `width` | int \| null | Image width in pixels |
| `height` | int \| null | Image height in pixels |
| `duration_s` | float \| null | Video duration in seconds; null for images |
| `sha256` | str | SHA-256 hex digest of the original file |
| `schema_version` | int | MediaMetadata schema version this record was extracted with (see "Lazy metadata refresh" below) |

---

### Lazy metadata refresh

Adding a new `MediaMetadata` field never requires re-ingesting existing
files. The extraction pipeline (`malmberg_server.ingest.media`) stamps every
freshly-extracted `MediaMetadata` with the current
`META_SCHEMA_VERSION`. When `GET /media` or `GET /media/{id}` serves an item
whose `meta.schema_version` is behind that constant, the server re-runs EXIF
extraction on the file in place, replaces `meta` (preserving
`do_not_display`, `hide_policy`, `tags`, `dwell_override_s`, and the original
`meta.ingest_at`), and persists the updated index to
`logs/media-index.jsonl`. If the source file is missing or extraction fails,
the stale record is served unchanged and a warning is logged; the refresh is
retried on the next read.

To add a new metadata field: add it to `MediaMetadata`, populate it in
`extract_exif`, and bump `META_SCHEMA_VERSION` by one. Existing items
self-heal the next time they are read.

`META_SCHEMA_VERSION` is currently `2` (bumped from `1` to add `meta.place`;
see below).

---

### Reverse geocoding (place names)

GPS-tagged photos (`meta.lat`/`meta.lon`, currently populated for iPhone
photos only -- most older cameras carry no GPS EXIF) are turned into a
human-readable `meta.place` label entirely offline, on the server, at ingest
time (`malmberg_server.ingest.media.reverse_geocode`). This never makes an
online request: it is a **best-effort** lookup against the `reverse_geocoder`
package's bundled offline cities dataset (`mode=1`, no multiprocessing pool).

- `reverse_geocoder` (which pulls in `numpy`/`scipy`) is **not** a base
  dependency -- it lives under a dedicated `geocode` optional extra in
  `pyproject.toml`, installed on the server only with
  `uv sync --extra geocode`. The Pi display never installs it.
- The import is best-effort (`try`/`except ImportError`): if the extra is not
  installed, `reverse_geocode` logs a warning once and returns `None` forever
  after -- ingestion and metadata refresh are unaffected, `meta.place` just
  stays `null`.
- `meta.place` feeds `GET /media?q=`, `GET /stats` (`by_place`), and
  `GET /places` (autocomplete) -- see those endpoints above.

---

## Display API

Default port: **8443**

### `GET /`

Returns an identity envelope for the display node.

**Response: `Tag`** -- same shape as the server's `GET /`, but `id` is always
`"display"` and `name` is `"Malmberg Display"`.

---

### `GET /status`

Returns the current slideshow state.

**Response: `DisplayStatus`**

| Field | Type | Description |
|-------|------|-------------|
| `paired_server` | str \| null | IP address of the paired server, or null if not yet paired |
| `online` | bool | Whether the display can reach the paired server |
| `current_item` | str \| null | `repr()` of the item currently being displayed; null before the first item |
| `queue_depth` | int | Number of pre-loaded items waiting in the producer queue |
| `paused` | bool | Whether the slideshow is paused |
| `history_count` | int | Number of items in the display history |

---

### `POST /slideshow/next`

Skip to the next item immediately. The display task dequeues the next pre-loaded
item without waiting for the current dwell time to expire.

**Response:**

```json
{ "status": "ok" }
```

---

### `POST /slideshow/prev`

Jump back to the previous item in the history deque.

**Response:**

```json
{ "status": "ok", "prev": "<repr of previous item>" }
```

**Errors:**
- `404` -- history has fewer than two entries (no previous item to go back to)

---

### `POST /slideshow/pause`

Toggle the slideshow between paused and running.

**Response:**

```json
{ "status": "paused" }
```

or

```json
{ "status": "resumed" }
```

---

### `GET /history`

Return the recent display history, newest first.

**Response:** list of `DisplayHistoryEntry`

| Field | Type | Description |
|-------|------|-------------|
| `item_repr` | str | `repr()` of the displayed item |

The history buffer holds the last `history_len` items (default 32, configurable in
`display.toml`).

---

### `POST /admin/restart`

Acknowledges with `{"status": "restarting"}`, then re-execs this display
process (`os.execv(sys.executable, [sys.executable, "-m", "malmberg_display"]`)
a fraction of a second later, mirroring the server's `POST /admin/restart`
(see above). The server's `POST /control/restart` proxies here.

**Response:**
```json
{ "status": "restarting" }
```

---

### Display-hosted dashboard: `GET /dashboard` + library proxy

The Display hosts a second accessor to the same photo library, so a user in
front of the frame (or on the same LAN) does not need to know the server's
address. `GET /dashboard` serves the identical dashboard page the server
serves (see `GET /dashboard` under Server API above) rendered with
`role="display"`: browse/details/delete/recycle-bin calls are proxied to
the paired server, but slideshow controls (Previous/Next/Pause, "Display it
now", "Play whole library", "Restart display") hit this display's own
routes directly -- no server round trip needed for those.

Only wired up when the display was built with both `server_url` and
`http_client` (i.e. it is paired with a server -- see
`malmberg_display.app.app.DisplayApp._run`); otherwise every proxy route
below responds `503`.

| Route | Forwards to (on the paired server) |
|-------|-------------------------------------|
| `GET /media` | `GET /media` (query params passed through) |
| `GET /media/trash` | `GET /media/trash` |
| `GET /media/{id}/thumb` | `GET /media/{id}/thumb` (streamed, not buffered) |
| `GET /media/{id}` | `GET /media/{id}` (streamed -- used for the in-dashboard `<video>` player too) |
| `GET /media/{id}/info` | `GET /media/{id}/info` |
| `GET /stats` | `GET /stats` |
| `GET /places` | `GET /places` (query params passed through) |
| `DELETE /media/{id}` | `DELETE /media/{id}` (`?permanent=` passed through) |
| `POST /media/{id}/restore` | `POST /media/{id}/restore` |
| `POST /media/bulk-delete` | `POST /media/bulk-delete` |
| `POST /control/restart-server` | `POST /admin/restart` (restarts the paired server itself) |

**Errors:**

| Status | Cause |
|--------|-------|
| `503` | Display is not paired with a server (`server_url`/`http_client` not configured) |
| `502` | The paired server could not be reached, or returned an error |
