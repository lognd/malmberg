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
| `q` | str | none | -- | Filters to items whose `filename` contains *q* (case-insensitive), whose `meta.taken_at` year equals *q* when *q* is a 4-digit year, whose `meta.taken_at` year and month equal *q* when *q* is `YYYY-MM`, whose `meta.place` contains *q* (case-insensitive), or (for `/media`) a detected person's name contains *q* |
| `q_time` | str | none | -- | Filters to items whose `meta.taken_at` matches a 4-digit year or `YYYY-MM`; the literal `unsorted` instead selects items with **no** date |
| `q_place` | str | none | -- | Filters to items whose `meta.place` contains *q_place* (case-insensitive); the literal `unsorted` instead selects items with **no** place |
| `q_person` | str | none | -- | Filters to items with a detected person whose name contains *q_person* (case-insensitive) |

`q_time`, `q_place`, and `q_person` are independent filters that combine with
each other, and with `q`, by **AND**: an item must satisfy every filter that
is given (e.g. `q_time=2006&q_place=Tampa` returns only 2006 photos taken in
Tampa). `q` alone keeps its original OR-across-fields behavior (used by the
dashboard's free-text search and by `POST /control/play-query`); the
dashboard's Time/Place/Person boxes use `q_time`/`q_place`/`q_person` so they
AND together instead of OR-matching a single combined box. See
`MediaStore._matches_filters` in `ingest/store.py`.

`q_time=unsorted` and `q_place=unsorted` (the `MediaStore.UNSORTED` sentinel,
case-insensitive) select the items *missing* that field entirely -- no
effective date, or no effective place. Screenshots, memes, and downloads
carry neither, so they never appear under any year or place and would
otherwise be unreachable through the breakdowns; `unsorted` is how the
dashboard filters them out of (or down to) a working set. A manual date/place
tag fills the effective field, so a tagged item stops being `unsorted`. Their
counts are `undated` and `unplaced` in `GET /stats`.

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

### `DELETE /people/{person_id}`

Delete a person group. **The photos are kept** -- only the grouping goes away,
along with the face embeddings that formed it.

Dropping the embeddings is not optional: `POST /people/recluster` rebuilds
people from the face index, so a person whose faces survived the delete would
simply reappear on the next recluster. Deleting them makes it stick.

The one caveat: this is not permanent against a face-pipeline version bump.
Raising `FACE_PROCESSING_VERSION` reprocesses each item from the photo itself,
re-detecting the faces, so a deleted junk cluster can come back after a model
or threshold upgrade. That is the honest trade for not touching the photos.

**Response:** `{"status": "deleted", "person_id": "...", "faces": <count>}`

**Errors:** `404` if the person does not exist.

---

### `GET /people`

List detected people (see "Face detection and search by person" below).
Backs the dashboard's "People" section.

**Query parameters**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `min_count` | int | `3` | 0--1000 | Hide clusters with fewer than this many photos (small/uncertain groups). Named people are always included. Pass `min_count=1` to fetch the small ones on demand. |

**Response:** `list[dict]`, each with:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Person id |
| `name` | str \| null | User-assigned display name; null until named |
| `count` | int | Distinct photos this person appears in |
| `sample_item_id` | str \| null | A media item id to use as a thumbnail |

Small clusters are never deleted or frozen: the worker keeps assigning new
matching faces to them, so a group can grow past `min_count` over time and
then become nameable. `min_count` is purely a display gate.

---

### `GET /people/{id}/photos`

Every face flagged for a person, for the dashboard review UI (green-box
overlay). Returns one row per face.

**Path parameters:** `id` -- the person id.

**Response:** `list[dict]`, each with:

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | str | Media item the face is in |
| `face_id` | str | Per-face record id (for `POST /faces/{id}/reassign`) |
| `bbox` | [int, int, int, int] | Face box `[x1, y1, x2, y2]` in source pixels |
| `img_w` | int \| null | Source image width (to scale the box onto the render) |
| `img_h` | int \| null | Source image height |

**Errors:** `404` -- unknown person id.

---

### `POST /faces/{face_id}/reassign`

Per-face manual override. Move one face to a different person, or detach it.

**Path parameters:** `face_id` -- from `GET /people/{id}/photos`.

**Request body:** `{"person_id": str | null}` -- a person id reassigns the
face to that existing person; `null` (or omitted) detaches it onto a new
unnamed person ("not this person"). Both affected people have their
centroid/count recomputed and empty unnamed people are pruned.

**Response:** `{"status": "reassigned", "face_id": ..., "person_id": ...}`.

**Errors:** `404` -- unknown face id, or a given target person id is unknown.

---

### `POST /people/{id}/merge`

Merge one person into another (fix an over-split). Reassigns every face of
`from_id` to `{id}`, drops `from_id`, and keeps `{id}`'s name.

**Path parameters:** `id` -- the surviving person id.

**Request body:** `{"from_id": str}` -- the person to merge in and remove.

**Response:** the surviving Person record.

**Errors:** `404` -- either id unknown, or the two ids are equal.

---

### `POST /people/recluster`

Rebuild all person groups from the per-face index using order-independent
single-linkage connected components (see below). Idempotent; user-assigned
names are preserved. Runs the clustering in a thread executor so the event
loop is never blocked.

**Response:** `{"status": "reclustered", "people": int, "faces": int}`.

---

### `POST /people/{id}/name`

Assign or change a detected person's display name.

If the given name is a near-duplicate of an existing named person's name,
this person is instead **merged into** that existing person (faces
reassigned, this person id dropped) rather than creating a second person
with essentially the same name; the existing person keeps its id and name.
Name matching is case-insensitive and trimmed, and tolerant of small typos
via Levenshtein edit distance (`<=1` for names of length `<=5`, `<=2`
otherwise -- see `PersonStore._find_duplicate_name` /
`PersonStore.rename_with_dedup` in `faces/people.py`). Otherwise, the name is
just set on `id`.

**Path parameters:** `id` -- the person id (from `GET /people`).

**Request body:** `{"name": str}`

**Response:** the "winning" Person record -- the existing person when a merge
happened, otherwise `id` with its new name.

**Errors:**
- `400` -- empty name
- `404` -- unknown person id

---

### `GET /people/suggest`

Autocomplete: distinct named-person display names containing a
prefix/substring, most-common first. Same shape as `GET /places`.

**Query parameters**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `q` | str | `""` | -- | Case-insensitive substring filter |
| `limit` | int | `10` | 1--50 | Maximum number of suggestions returned |

**Response:** `list[str]` -- person names, e.g. `["Grandma"]`.

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

### `POST /media/{id}/tag`

Set or clear a manual date/location override on a single item -- for old
scans and camera-less photos that have no EXIF `DateTimeOriginal` or GPS and
would otherwise never show up in the year/month time filters or place
search/stats.

**Request body: `MediaTagRequest`** -- every field is optional and
independent. A field **omitted** from the body is left unchanged. A field
**explicitly sent as `null`** clears that manual override, reverting to the
photo's own EXIF value.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string \| null | ISO date (`YYYY-MM-DD`) or full ISO datetime. Stored as `meta.manual_taken_at` (UTC). |
| `place` | string \| null | Free-text place label, e.g. `"Grandma's house, Tampa"`. Stored as `meta.manual_place`. |
| `lat` | float \| null | Latitude. Stored as `meta.manual_lat`. |
| `lon` | float \| null | Longitude. Stored as `meta.manual_lon`. |

If `lat`/`lon` are given without an explicit `place`, they are reverse
-geocoded (best-effort, offline, same `reverse_geocode()` used at ingest)
into `meta.manual_place`. An explicit `place` always wins over a derived
one, even when coordinates are also given.

**Response:** the updated `MediaItem`.

**Errors:**
- `400` -- `date` could not be parsed
- `404` -- item not found

---

### `POST /media/tag-bulk`

Apply the same manual date/location to many items in one call (e.g. an
entire batch of scans from one event).

**Request body: `MediaTagBulkRequest`** -- `MediaTagRequest`'s fields plus:

| Field | Type | Description |
|-------|------|-------------|
| `ids` | list[str] | Item ids to tag |

**Response:**

```json
{"tagged": ["id1", "id2"], "failed": ["id3"]}
```

A failure on one id (not found, or an invalid `date`) does not abort the
rest.

---

### `POST /media/{id}/transform`

Permanently rotate and/or flip an image, baking the change into the pixels
of the file on disk. Images only -- this is not supported for videos.

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `rotate` | int | One of `0` (default), `90`, `180`, `270`, `-90` (== `270`). Degrees clockwise. |
| `flip` | `"h"` \| `"v"` \| null | Horizontal or vertical flip, applied after the rotate. |

Any EXIF orientation the file already carried is normalized into the pixels
first (so the requested transform composes correctly with however the file
was already oriented), then the requested rotate/flip is applied. GPS,
`DateTimeOriginal`, `Make`/`Model`, and the rest of the EXIF block are
preserved byte-for-byte; only the `Orientation` tag is reset to `1`
(normal) so viewers never double-rotate the result.

**This rewrites the file's bytes, which invalidates four things -- all
handled by this one endpoint:**

1. `meta.sha256`, `meta.width`, `meta.height` are recomputed from the
   rewritten file (dimensions swap on a 90/270 rotate) and the index is
   persisted.
2. Every cached thumbnail for the item (`/fs/.thumbs/{id}_*.jpg`) is
   deleted so it regenerates from the new pixels on next request.
3. The paired display's `ServerProducer` download cache is keyed by
   `meta.sha256` (not just item id), so once the display next lists this
   item it sees the new digest, misses its old cache entry, and
   re-downloads -- it will not keep showing the stale orientation.
4. **Any cloud-sync record tracking this item is marked `verified=false`.**
   The local copy is no longer byte-identical to the cloud original, so it
   must not keep reading as verified -- this is what prevents the guarded
   cloud-cleanup (`POST /cloud/delete`) from deleting the cloud original
   out from under an edited local copy. Re-verification will simply fail
   until/unless the cloud copy is re-synced to match.

**Response:** the updated `MediaItem`.

**Errors:**
- `400` -- attempted on a video, or on a trashed item
- `404` -- item not found, or its file is missing from disk
- `422` -- the file could not be decoded or re-encoded

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

### `POST /control/play-query`

Build a play set from a filter and show only those photos on the display
(forwarded to the display's `/slideshow/playlist`).

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | str | none | Single free-text filter (OR across filename / year / month / place / person), same matcher as `GET /media?q=` |
| `q_time` | str | none | Time filter: a 4-digit year or `YYYY-MM` against `meta.taken_at`, or `unsorted` for items with no date |
| `q_place` | str | none | Place substring (case-insensitive) against `meta.place`, or `unsorted` for items with no place |
| `q_person` | str | none | Named-person substring against the item's detected people |
| `loop` | bool | `false` | `false` plays the set once then returns to the whole library; `true` repeats until "play all" |

`q_time` / `q_place` / `q_person` combine with each other (and with `q`) by
**AND** -- exactly like `GET /media` -- so the dashboard's frame Time / Place /
Person boxes play only photos matching all filled-in boxes. At least one
non-empty filter is required. The dashboard's year/month quick-buttons post
`q_time`; the free-text `q` path remains for other callers.

**Response:** the display's `/slideshow/playlist` JSON, passed through.

**Errors:**

| Status | Cause |
|--------|-------|
| `400` | No non-empty filter given |
| `404` | No photos match the filter |
| `503` | No `display_url` configured on the server |
| `502` | The display could not be reached, or returned an error |

---

### `GET /cloud/status`

Per-provider cloud-sync diagnostics.

**Response:** `CloudStatus`

| Field | Type | Description |
|-------|------|-------------|
| `providers` | list[ProviderStatus] | One block per registered provider |

Each `ProviderStatus`:

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Provider machine name (`icloud`, `google_photos`) |
| `enabled` | bool | Whether the provider's enable flag is set in config |
| `configured` | bool | Whether the optional dependency and credentials are present |
| `tracked` | int | Remote items tracked in the sync state |
| `verified` | int | Tracked items whose local copy matched by SHA-256 |
| `deleted_from_cloud` | int | Tracked items already deleted from the cloud |
| `last_sync_at` | str \| null | ISO-8601 timestamp of the last sync, or null |
| `last_error` | str \| null | Last sync error text, or null |

---

### `POST /cloud/sync`

Schedule an immediate sync (runs as a background task; returns at once).

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | str \| null | `null` | Limit to one provider by name; null syncs all registered providers |

**Response:** `CloudSyncAck`

| Field | Type | Description |
|-------|------|-------------|
| `status` | str | `"started"`, `"no_providers"`, or `"unknown_provider"` |
| `providers` | list[str] | Provider names the sync was started for |

---

### `GET /cloud/deletable`

Dry-run list of remote items verified (re-hashed from disk right now) as safe
to delete. Deletes nothing.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | str | Provider name (required) |

**Response:** `DeletablePage`

| Field | Type | Description |
|-------|------|-------------|
| `provider` | str | Provider name |
| `items` | list[DeletableEntry] | Items verified safe to delete |
| `total` | int | Number of deletable items |

**Errors:** `404` if the provider is unknown.

---

### `POST /cloud/delete`

Delete cloud items that re-verify against their local copy. Guarded: refuses
without an explicit `confirm`, deletes only verified items, and caps the number
deleted per call. Every deletion is written to `fs_root/logs/cloud-deletions.log`.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | str | required | Provider name |
| `confirm` | bool | `false` | Must be `true`; a `false` value is rejected with `400` |
| `cap` | int \| null | `null` | Per-run deletion cap; null uses `cloud_delete_cap` (effective cap is `min(cap, cloud_delete_cap)`) |

**Response:** `DeleteReport`

| Field | Type | Description |
|-------|------|-------------|
| `provider` | str | Provider name |
| `dry_run` | bool | Always `false` for this endpoint (confirm is required) |
| `candidates` | int | Items verified deletable at the start of the run |
| `deleted` | int | Items actually deleted from the cloud |
| `skipped_unverified` | int | Candidates that failed re-verification at delete time |
| `failed` | int | Delete attempts that errored (e.g. provider cannot delete) |
| `capped` | bool | Whether the run stopped at the cap |
| `errors` | list[str] | Per-item error messages |

**Errors:**

| Status | Cause |
|--------|-------|
| `400` | `confirm` not `true`, or the provider cannot delete (`Unsupported`) |
| `404` | Unknown provider |
| `502` | Provider auth/network error |
| `500` | Audit log or sync-state write failure |

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
| `person_ids` | list[str] | `[]` | IDs of detected `Person` records (see "Face detection and search by person" below); populated asynchronously by the background face worker, not at ingest time |
| `faces_processed` | bool | `false` | Whether the background face worker has attempted detection on this item at least once |
| `faces_version` | int | `0` | Face-pipeline version this item was last processed with; items behind `FACE_PROCESSING_VERSION` are transparently reprocessed by the worker (self-heal after a model/threshold/schema change) |

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
| `manual_taken_at` | ISO 8601 datetime \| null | User-entered date override, set via `POST /media/{id}/tag` or `/media/tag-bulk`; null unless set |
| `manual_lat` | float \| null | User-entered latitude override; null unless set |
| `manual_lon` | float \| null | User-entered longitude override; null unless set |
| `manual_place` | str \| null | User-entered (or coordinate-derived) place label override; null unless set |
| `effective_taken_at` | ISO 8601 datetime \| null | **Computed, read-only.** `manual_taken_at` if set, else `taken_at`. Every consumer that needs "the" date of a photo (search, stats, display captions) reads this. |
| `effective_lat` | float \| null | **Computed, read-only.** `manual_lat` if set, else `lat`. |
| `effective_lon` | float \| null | **Computed, read-only.** `manual_lon` if set, else `lon`. |
| `effective_place` | str \| null | **Computed, read-only.** `manual_place` if set, else `place`. |

#### Manual date/location overrides

`manual_taken_at`/`manual_lat`/`manual_lon`/`manual_place` exist to let a
user hand-date and hand-locate photos with no EXIF `DateTimeOriginal` and no
GPS (old scans, cameras without a clock or GPS) -- see `POST /media/{id}/tag`
and `POST /media/tag-bulk`. They are stored as **separate fields from** the
EXIF-derived `taken_at`/`lat`/`lon`/`place`, specifically so that the lazy
metadata refresh (below) and `POST /media/{id}/transform` -- both of which
re-extract EXIF straight from the file and would otherwise overwrite those
fields -- can never silently wipe a manual tag. Both preserve
`manual_taken_at`/`manual_lat`/`manual_lon`/`manual_place` explicitly when
they replace `meta`.

Every place in the server that answers "what is this photo's date/place"
(search by year/month/place, `GET /stats`'s `by_year`/`by_month`/`by_place`/
`undated`/`unplaced`, `GET /places` autocomplete, and the `meta` served in `GET /media`
that feeds the paired display's on-screen caption) reads the `effective_*`
computed fields, not the raw EXIF fields, so a manually-tagged photo behaves
identically to one with real EXIF everywhere in the app.

---

### Lazy metadata refresh

Adding a new `MediaMetadata` field never requires re-ingesting existing
files. The extraction pipeline (`malmberg_server.ingest.media`) stamps every
freshly-extracted `MediaMetadata` with the current
`META_SCHEMA_VERSION`. When `GET /media` or `GET /media/{id}` serves an item
whose `meta.schema_version` is behind that constant, the server re-runs EXIF
extraction on the file in place, replaces `meta` (preserving
`do_not_display`, `hide_policy`, `tags`, `dwell_override_s`, the original
`meta.ingest_at`, and the manual override fields `manual_taken_at`/
`manual_lat`/`manual_lon`/`manual_place`), and persists the updated index to
`logs/media-index.jsonl`. If the source file is missing or extraction fails,
the stale record is served unchanged and a warning is logged; the refresh is
retried on the next read. `POST /media/{id}/transform` re-extracts EXIF the
same way after rewriting the file's pixels and preserves the same manual
override fields for the same reason.

To add a new metadata field: add it to `MediaMetadata`, populate it in
`extract_exif`, and bump `META_SCHEMA_VERSION` by one. Existing items
self-heal the next time they are read.

`META_SCHEMA_VERSION` is currently `2` (bumped from `1` to add `meta.place`;
see below).

---

### Reverse geocoding (place names)

GPS-tagged photos (`meta.lat`/`meta.lon`, currently populated for iPhone
photos only -- most older cameras carry no GPS EXIF) are turned into a
human-readable `meta.place` label entirely offline, on the server
(`malmberg_server.ingest.gazetteer`). This never makes an online request.

**The dataset.** We ship GeoNames cities500 (every populated place down to
~500 people, 225k rows, gzipped in `malmberg_server/data/cities500.csv.gz`,
CC BY 4.0). We used to use `reverse_geocoder`'s bundled list, but it is
cities1000 filtered down further and the gaps are not where you would guess:
**Batam** -- an Indonesian city of 1.3 million people, 25 km across the strait
from Singapore -- is absent from it entirely. Nearest-city lookup therefore
labelled every photo taken on Batam (and across the Riau archipelago)
"Singapore, SG"; that was 1,382 photos in the real library.

**The picking rule.** A denser dataset alone makes nearest-city *too* literal:
the closest populated place to a photo taken in downtown Singapore is a new
town like Ang Mo Kio, which shatters "Singapore" into districts. So the closest
place wins by default, but a neighbour takes the label off it only by being
`_DOMINANCE` (10x) larger, within `_NEARBY_SLACK_KM` (12 km):

| Photo taken in | Closest place | Nearby giant | Label | Why |
|---|---|---|---|---|
| Nongsa, Batam | Batam (1.3M) | Singapore is 29 km away | `Batam, Riau, ID` | Singapore is not even a candidate |
| Sekupang, Batam | Sekupang (pop 0) | Batam, 9 km | `Batam, Riau, ID` | anything populated dominates a 0 |
| Ang Mo Kio | Ang Mo Kio (174k) | Singapore (3.5M), 7 km | `Singapore, SG` | 20x bigger: a city swallows its districts |
| Oxelosund, SE | Oxelosund (11k) | Nykoping (30k), 11 km | `Oxelosund, ...` | only 3x bigger: a town does not swallow its neighbour |
| Mid-Atlantic | nothing within 60 km | -- | `null` | no label beats a misleading one |

Place names carry their real spelling (accents and all -- the dataset is UTF-8,
and being a gzipped blob it costs the codebase no non-ASCII source).

**Your own places.** `<fs_root>/geocode-extra.csv` (columns
`lat,lon,name,admin1,cc,population`) is merged on top of the dataset if
present, for what no public gazetteer will ever have -- a cabin, a family farm,
"Grandma's house". Custom rows are **exempt from the dominance rule**: if the
user says a spot on the map is Grandma's house, a photo taken there says
Grandma's house and no city outvotes it. A malformed row is logged and skipped,
never fatal.

**Reaching the photos already in the library.** `meta.geo_version` records the
`GAZETTEER_VERSION` each label was produced with, and
`malmberg_server.ingest.regeocode.run_regeocode_worker` (a background task,
started at server startup) recomputes `place` for every item behind the current
version. It works off the lat/lon already in the index, so it touches no photo
files at all: no decode, no re-hash, no EXIF re-read. That is why the gazetteer
has its own version counter rather than riding on `META_SCHEMA_VERSION`, whose
bump would force a full re-extract of every file in the library to fix a
string. A user-set `manual_place` is never overwritten.

- The `geocode` extra (`uv sync --extra geocode`) is just `numpy` now -- the
  lookup is one vectorized distance pass over the dataset (~9 ms). It is
  installed on the server only; the Pi never runs this.
- If numpy or the dataset is unavailable, a warning is logged once and
  `reverse_geocode()` returns `None` forever after -- ingestion and metadata
  refresh are unaffected, `meta.place` just stays `null`. It never raises into
  its caller.
- `meta.place` feeds `GET /media?q=`, `GET /stats` (`by_place`), and
  `GET /places` (autocomplete) -- see those endpoints above.
- The display reads the server's label as `meta.effective_place` and renders
  it directly in the photo caption (`ServerProducer._item_from_raw` ->
  `PictureDisplay` -> `ImageCaption.from_metadata`). Because the Pi has no
  geocoder dataset of its own, this is the only source of a real place name on
  the frame: without it the caption can only fall back to decimal coordinates.

---

### Thumbnails and the background warmer

`GET /media/{id}/thumb?size=` serves a cached JPEG thumbnail, generating it on
first request. Generating one means a full-resolution decode of the original (a
12 MP HEIC, or a video poster frame), which is far too slow to sit on the
request path of whoever happens to turn the page first.

So `malmberg_server.ingest.thumbs.run_thumb_worker` -- an asyncio background
task started from the server's FastAPI startup event, alongside the face worker
-- walks the library in small batches and writes the missing thumbnails ahead of
the user, at the sizes the dashboard actually browses at (`WARM_SIZES`: 400 for
the grid and face-review cards, 200 for the people cards and frame preview). The
on-disk file *is* the state: an existing thumbnail is skipped, a deleted one is
regenerated, trashed items are not warmed. Cheap to re-run, safe to interrupt.

The larger sizes (the 1200 face zoom) stay lazy: they are opened one photo at a
time, not a gridful at once, so warming them would cost a decode per item for a
request that mostly never comes.

Because the thumbnails are already on disk, the dashboard can afford to prefetch
the *next* page's thumbnails while the user is still looking at the current one
(`prefetchNextPage` in `api/web.py`), which is what makes paging feel instant.
Paging also takes a "go to page N" jump box -- at 24 photos a page, a 17k-item
library is ~700 pages and stepping there with Next is not a plan.

---

### Face detection and search by person

Faces are detected and clustered into people entirely server-side, entirely
offline, and entirely off the request path.

- **Stack:** `insightface` on CPU via `onnxruntime`, using the `buffalo_l`
  model pack (larger RetinaFace detector + ArcFace 512-d embedder -- notably
  better embeddings than `buffalo_s`; the x86_64 server has the headroom, the
  Pi never runs this). The pack name is the single constant
  `malmberg_server.faces.detect.MODEL_PACK`; it downloads once on first use
  into `fs_root/.faces/models`. Both packages live under a dedicated `faces`
  optional extra in `pyproject.toml`, installed on the server only with
  `uv sync --extra faces`. The Pi display never installs it and
  `malmberg_display` never imports `malmberg_server.faces.detect` -- the
  display's dashboard only talks to the server's `/people*` and `/faces*`
  endpoints over HTTP, same as it does for `/places`.
- The model-pack import is best-effort (`malmberg_server.faces.detect`,
  `try`/`except ImportError`, mirroring `reverse_geocode`): if the extra is
  not installed, or model load / a single detection call fails for any
  reason, a warning is logged and `detect_faces()` returns `[]` -- it never
  raises into its caller.
- **Quality filtering:** detections below `MIN_DET_SCORE` (detector
  confidence, `0.6`) or smaller than `MIN_FACE_AREA_FRAC` of the image
  (`0.005`, i.e. tiny background faces) are dropped before clustering, since
  they otherwise create spurious singleton people and mis-groupings.
- **Per-face index:** `malmberg_server.faces.faces_index.FaceStore` persists
  one record per detected face at `logs/faces.jsonl` -- `{face_id, item_id,
  person_id, bbox, det_score, embedding}`. This is the source of truth for
  face -> person membership; a `Person`'s centroid/count are always *derived*
  from it, which is what makes order-independent reclustering and per-face
  overrides recompute cleanly.
- **Background processing, never inline:** `malmberg_server.faces.worker`
  runs as an asyncio background task (started from the server's FastAPI
  startup event), sweeping the media index in small batches for items that
  are unprocessed *or* were processed by an older `FACE_PROCESSING_VERSION`.
  Each item's actual `detect_faces()` call runs in a thread executor
  (`loop.run_in_executor`), so the event loop -- and uploads -- are never
  blocked. `POST /upload` returns immediately; faces fill in afterward.
- **Online grouping:** `PersonStore.assign` uses single-linkage
  max-similarity -- a new face joins the existing person with the highest
  cosine similarity to *any one* of that person's stored face embeddings, if
  that similarity is at least `cluster.SIMILARITY_THRESHOLD` (`0.4`, tuned for
  buffalo_l L2-normalized ArcFace; max-linkage tracks a person across pose and
  lighting far better than a drifting running-average centroid). Otherwise a
  new unnamed `Person` is created. Persisted at `logs/people.jsonl`.
- **Batch recluster:** once the worker drains its backlog it runs one
  `PersonStore.recluster` -- order-independent single-linkage connected
  components (`cluster.connected_components`) over every stored embedding --
  so the final groups do not depend on ingest order. It also runs on demand
  via `POST /people/recluster`. User-assigned names are preserved by matching
  each rebuilt cluster to the old person the plurality of its faces belonged
  to. This is also how a model or threshold change takes effect on the
  existing library, via the reprocess (`FACE_PROCESSING_VERSION`) + recluster
  self-heal path -- no manual step.
- **Group photos land under every person in them.** Each detected face is
  assigned independently, so a photo of three people is filed under all three:
  `MediaItem.person_ids` collects every person found in it, each person's photo
  count credits it, and searching by any one of them returns it. There is no
  "primary" face.
- **Manual overrides:** `POST /faces/{id}/reassign` moves or detaches a single
  face; `POST /people/{id}/merge` merges two people; `DELETE /people/{id}`
  removes a junk cluster outright (photos kept -- see that endpoint above). All
  recompute the affected people from the per-face index and re-project
  `person_ids` onto the media items.
- **Acting on photos from review:** the dashboard's per-person review modal can
  soft-delete a photo (`DELETE /media/{id}`) and open the standard item modal
  (rotate / flip / tag / play) for any face card, so the junk found while
  reviewing a person can be dealt with without leaving the modal. A trashed
  photo is filtered out of `GET /people/{id}/photos`, keeping the review grid
  and the person's displayed count in step.
- Each `MediaItem` carries `person_ids: list[str]` (people detected in it),
  `faces_processed: bool`, and `faces_version: int`. These are plain fields
  with safe defaults, not part of `MediaMetadata`'s schema-refresh cycle --
  face processing is expensive, so it is only ever done by the background
  worker, never by the lazy per-request metadata refresh described above.
- `person_ids` (resolved to names via `PersonStore`) feed `GET /media?q=`,
  `GET /stats` (`by_person`), `GET /people`, and `GET /people/suggest`.
  `POST /control/play-query?q=<name>` plays a named person's photos on the
  frame exactly like it does for a place or year, since person names are
  matched by the same `_matches_query`.

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
| `GET /people` | `GET /people` (query params passed through) |
| `GET /people/{id}/photos` | `GET /people/{id}/photos` |
| `POST /people/{id}/name` | `POST /people/{id}/name` |
| `POST /people/{id}/merge` | `POST /people/{id}/merge` |
| `POST /people/recluster` | `POST /people/recluster` |
| `POST /faces/{id}/reassign` | `POST /faces/{id}/reassign` |
| `GET /people/suggest` | `GET /people/suggest` (query params passed through) |
| `DELETE /media/{id}` | `DELETE /media/{id}` (`?permanent=` passed through) |
| `POST /media/{id}/restore` | `POST /media/{id}/restore` |
| `POST /media/bulk-delete` | `POST /media/bulk-delete` |
| `POST /media/{id}/tag` | `POST /media/{id}/tag` |
| `POST /media/tag-bulk` | `POST /media/tag-bulk` |
| `POST /control/restart-server` | `POST /admin/restart` (restarts the paired server itself) |
| `GET /cloud/status` | `GET /cloud/status` (read-only cloud-sync diagnostics) |
| `GET /cloud/deletable` | `GET /cloud/deletable` (query params passed through; read-only dry run) |

Only the two read-only cloud routes are proxied. `POST /cloud/sync` and
`POST /cloud/delete` are server-only writes and are intentionally **not**
proxied; the display dashboard hides the "Sync now" and "Clean up cloud"
buttons in the `role="display"` render.

**Errors:**

| Status | Cause |
|--------|-------|
| `503` | Display is not paired with a server (`server_url`/`http_client` not configured) |
| `502` | The paired server could not be reached, or returned an error |
