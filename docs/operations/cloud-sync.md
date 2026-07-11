# Cloud photo sync

Malmberg can pull photos down from cloud accounts (Google Photos, iCloud) into
your local library, and -- only after verifying the local copy byte-for-byte --
optionally delete them from the cloud to reclaim space. This document covers
one-time setup for each provider, the background auto-sync, and the deletion
safety model.

Cloud sync is server-only. The display never touches cloud providers; it only
proxies the two read-only cloud endpoints so its dashboard can show status.

## Provider dependencies

Each provider lives behind an optional dependency extra so a Raspberry Pi
display install never pulls cloud libraries:

```
uv sync --extra cloud-googlephotos    # Google Photos
uv sync --extra cloud-icloud          # iCloud
```

If an extra is not installed, that provider reports itself "Not set up" and is
skipped -- nothing crashes.

## Google Photos

### Important limitation (read first)

Since the Google Photos Library API policy change enforced around **March 2025**,
third-party apps can only see and download **media the app itself uploaded**.
Malmberg **cannot** access your full existing Google Photos library, and the
Library API exposes **no delete operation at all**. Connecting Google Photos is
therefore useful only for app-uploaded content, and `POST /cloud/delete` for
Google Photos always reports the items as failed (`Unsupported`) rather than
faking success. Clean up your real Google Photos library manually in the Google
Photos UI.

### Setup

1. Create a project at <https://console.cloud.google.com/>.
2. Enable the **Photos Library API** for that project.
3. Configure the **OAuth consent screen** (External; add yourself as a test user).
4. Create an **OAuth client ID** of type **Desktop app**.
5. Download the client secret JSON (e.g. `path/to/credentials.json`).
6. Run the setup script (installs the token under `fs_root/.cloud/`):

   ```
   uv run python scripts/cloud_setup_google.py --fs-root /fs \
       --credentials path/to/credentials.json
   ```

7. Enable the provider on the server:

   ```
   export MALMBERG_CLOUD_GOOGLE_PHOTOS_ENABLED=1
   ```

## iCloud

### Important warning (read first)

The iCloud provider uses **pyicloud**, which drives Apple's **unofficial,
private** web API. It is not sanctioned by Apple, can **break without notice**
when Apple changes their endpoints, and its cached session **expires
periodically** (you will need to re-run the setup script). Treat iCloud sync as
**best-effort**. Deletion moves items to iCloud's "Recently Deleted" album,
where Apple retains them for roughly 30 days.

### Setup

1. Generate an **app-specific password** at <https://appleid.apple.com>
   (Sign-In and Security -> App-Specific Passwords). Do not use your main
   Apple ID password.
2. Run the setup script and complete the 2FA prompt; the session is cached
   under `fs_root/.cloud/icloud-session/`:

   ```
   uv run python scripts/cloud_setup_icloud.py --fs-root /fs
   ```

3. Enable the provider and supply credentials on the server:

   ```
   export MALMBERG_CLOUD_ICLOUD_ENABLED=1
   export MALMBERG_CLOUD_ICLOUD_USERNAME=you@example.com
   export MALMBERG_CLOUD_ICLOUD_PASSWORD=your-app-specific-password
   ```

   The password is read only from the environment; it is never stored in the
   Malmberg config.

## Auto-sync configuration

A background task on the server periodically pulls from every enabled and
configured provider. It **only ever pulls** -- it never deletes.

| Env var | Default | Meaning |
|---------|---------|---------|
| `MALMBERG_CLOUD_ICLOUD_ENABLED` | `false` | Enable the iCloud provider |
| `MALMBERG_CLOUD_ICLOUD_USERNAME` | (none) | Apple ID for iCloud |
| `MALMBERG_CLOUD_ICLOUD_SESSION_DIR` | `fs_root/.cloud/icloud-session/` | Cached pyicloud session dir |
| `MALMBERG_CLOUD_GOOGLE_PHOTOS_ENABLED` | `false` | Enable the Google Photos provider |
| `MALMBERG_CLOUD_GOOGLE_CLIENT_SECRETS` | `fs_root/.cloud/google-client-secret.json` | OAuth client secret path |
| `MALMBERG_CLOUD_GOOGLE_TOKEN` | `fs_root/.cloud/google-photos-token.json` | OAuth token path |
| `MALMBERG_CLOUD_SYNC_INTERVAL_S` | `3600` | Seconds between auto-sync sweeps (min 60) |
| `MALMBERG_CLOUD_DELETE_CAP` | `200` | Hard ceiling on deletions per cleanup run (min 1) |

The app-specific iCloud password is passed via `MALMBERG_CLOUD_ICLOUD_PASSWORD`
and is never persisted.

## Diagnostics

`GET /cloud/status` returns per-provider counters: whether the provider is
enabled and configured, the number of tracked / verified / already-deleted
items, the last sync time, and the last error. The dashboard's "Cloud photos"
section renders this, and the CLI prints it:

```
uv run python scripts/cloud_sync.py show-status
uv run python scripts/cloud_sync.py sync --provider icloud
```

## Deletion safety model

Deleting from the cloud is deliberately hard to do by accident. All of the
following hold, in order (see `malmberg_server.cloud.verify_and_delete`):

1. **Verified-by-SHA-256 only.** An item is deletable only if its local copy
   exists, is not trashed, and its file **re-hashed from disk right now**
   matches the digest recorded at sync time (`CloudSyncEngine.verify_record`).
   The cached `verified` flag in the state file is never trusted for deletion;
   every candidate is re-verified at decision time and again immediately before
   its remote delete.
2. **Dry-run by default.** `GET /cloud/deletable` and `POST /cloud/delete` with
   `confirm=false` run the identical selection logic and delete nothing.
3. **Explicit opt-in confirm.** `POST /cloud/delete` refuses with `400` unless
   the body sets `confirm: true`. The dashboard shows a strong `confirm()`
   dialog naming the count and provider before sending it.
4. **Hard cap.** At most `min(request cap, cloud_delete_cap)` items are deleted
   per run (default cap 200). Callers can only lower the cap, never raise it.
5. **Audit log.** For each deletion an `intent` line is appended to
   `fs_root/logs/cloud-deletions.log` **before** the remote call, followed by a
   `deleted` or `failed` outcome line. If the intent line cannot be written the
   run aborts before touching the provider. Each line is JSON: timestamp,
   provider, remote_id, local_item_id, sha256, filename, action.

The background auto-sync worker **never** calls the deletion path -- cleanup is
always an explicit, human-initiated action.
