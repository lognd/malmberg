# Server Features

## 5.1 Provisioning Script (`malmberg_server.setup`)

Invoked as `python -m malmberg_server setup` (enforces `sudo` if not root).
Idempotent. Steps:

1. Detect hardware; write `hardware.toml`.
2. Create system user `malmberg` with no login shell.
3. Create `/fs` owned by `malmberg:malmberg`, mode 750.
4. Create ZFS dataset `tank/malmberg` mounted at `/fs` (skip if exists).
5. Install `uvicorn` and system dependencies.
6. Write a `systemd` service unit `malmberg-server.service` and enable it.
7. Generate a self-signed TLS cert/key pair in `/etc/malmberg/tls/`.
8. Write the pairing PIN to the status panel (or print it to console if no panel).
9. Print a human-readable summary with any manual steps remaining.

## 5.2 File Ingest

**Phone upload (HTTPS):**
`POST /upload` accepts `multipart/form-data`. Files are streamed to `uploads/`,
hash-verified (SHA-256), EXIF-parsed, then moved to `media/YYYY/MM/DD/`. The
API returns a JSON receipt with the final path. Max upload size is configurable
(default 500 MB per file).

**USB:**
A `systemd` udev rule triggers `malmberg_server.ingest.usb` when a USB mass
storage device appears. The service mounts the device, enumerates known media
extensions, copies new files (deduplication by SHA-256), then safely unmounts.
The status panel shows progress during the operation.

**Cloud sync:**
Plugin-based. Each provider implements `CloudProvider(ABC)`:

```python
class CloudProvider(ABC):
    name: str           # e.g. "icloud", "googlephotos"
    account: str        # user-supplied label; multiple accounts per provider

    @abstractmethod
    async def poll(self) -> AsyncIterator[MediaItem]: ...

    @abstractmethod
    async def download(self, item: MediaItem, dest: Path) -> None: ...
```

Providers ship in `malmberg_server.ingest.cloud`. Multiple instances of the
same provider are supported. Each instance is configured as a separate table
in `server.toml`:

```toml
[[cloud.provider]]
type = "icloud"
account = "moms-icloud"
username = "mom@example.com"

[[cloud.provider]]
type = "googlephotos"
account = "dads-google"
```

Cloud providers are **opt-in**: no provider packages are installed unless the
corresponding `[cloud-icloud]` or `[cloud-googlephotos]` pip extra is
installed.

Token storage is encrypted at rest using `cryptography.fernet` with a key
derived from a user-supplied passphrase (stored in kernel keyring via
`keyring`).

## 5.3 File API

All endpoints require a completed mutual-TLS handshake (paired peer).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Returns `Tag` (name, id, version, mac) |
| GET | `/media` | Paginated list of media items with metadata |
| GET | `/media/{id}` | Stream a single file |
| GET | `/media/{id}/thumb` | JPEG thumbnail (generated lazily, cached) |
| POST | `/upload` | Ingest a new file |
| PATCH | `/media/{id}` | Update tags (e.g. `do_not_display`, `trash_on_hide`) |
| DELETE | `/media/{id}` | Act per `trash_on_hide` policy |
| GET | `/status` | Machine health (disk usage, uptime, peer list, mode) |
| GET | `/history` | Audit log of recent ingest and deletion events |
| GET | `/logs` | Rolling log tail (paginated, plain text) |
| GET | `/logs/events` | Structured event stream (JSON lines, filterable) |
| GET | `/backup/history` | Backup audit log |

## 5.4 "Do Not Display" Policy

When the user hides an item, the Display calls `DELETE /media/{id}`. The Server
applies the configured `hide_policy`:

| `hide_policy` value | Behavior |
|---------------------|----------|
| `"delete"` (default) | File is moved to `.trash/`; purged on schedule |
| `"keep"` | File is tagged `do_not_display=true`; stays in `media/`; never served |

`hide_policy` is a global default in `server.toml` and can be overridden
per-item via `PATCH /media/{id}`. Trash is purged on a configurable schedule
(default: 30 days).

## 5.5 Backup

See [backup.md](backup.md).
