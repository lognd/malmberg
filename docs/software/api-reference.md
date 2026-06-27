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

### `GET /media`

Returns a paginated list of media items. Hidden items (`do_not_display=true`) are
excluded.

**Query parameters**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `page` | int | `1` | >= 1 | Page number (1-based) |
| `page_size` | int | `50` | 1--500 | Items per page |

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

**Errors:**
- `404` -- item not found in the index, or the file is missing from disk

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

Apply the hide policy for a media item.

The action taken depends on the item's `hide_policy` field (which can be set via
`PATCH` before calling `DELETE`):

| `hide_policy` | Action |
|---------------|--------|
| `"delete"` (default) | File is moved to `/fs/.trash/`; item is removed from the index |
| `"keep"` | Item is tagged `do_not_display=true`; file stays in `/fs/media/` |

**Response:**

```json
{ "status": "trashed", "id": "..." }
```

or

```json
{ "status": "hidden", "id": "..." }
```

**Errors:**
- `404` -- item not found

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

### `MediaMetadata`

| Field | Type | Description |
|-------|------|-------------|
| `taken_at` | ISO 8601 datetime \| null | `DateTimeOriginal` from EXIF; null if absent or not an image |
| `ingest_at` | ISO 8601 datetime | When the file was received by the server (always set) |
| `camera_model` | str \| null | Camera make and model from EXIF |
| `lat` | float \| null | GPS latitude in decimal degrees (positive = north) |
| `lon` | float \| null | GPS longitude in decimal degrees (positive = east) |
| `width` | int \| null | Image width in pixels |
| `height` | int \| null | Image height in pixels |
| `duration_s` | float \| null | Video duration in seconds; null for images |
| `sha256` | str | SHA-256 hex digest of the original file |

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
