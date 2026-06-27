# Provisioning

This page covers production setup for both roles. For a quick single-machine test
see [Getting started](../getting-started.md).

---

## Server provisioning (Ubuntu 22.04+)

### Prerequisites

- Ubuntu 22.04 LTS or later (other distros work but are untested)
- Python 3.10+: `python3 --version`
- `systemctl` and `useradd` available (standard on systemd-based distros)
- ZFS strongly recommended; install before running setup:
  ```bash
  sudo apt install zfsutils-linux
  ```
- At least 8 GB RAM; mirrored storage for production
- `uv` package manager installed

The setup script validates the environment before making any changes. If `zfs` is
not on PATH it logs a warning with install instructions and continues -- the server
works without ZFS but snapshot-based backups are unavailable.

### 1. Set up ZFS (recommended)

Create a mirrored pool and dataset before running the provisioning script. Replace
`/dev/sdb` and `/dev/sdc` with your actual drives:

```bash
sudo zpool create -o ashift=12 tank mirror /dev/sdb /dev/sdc
sudo zfs set compression=lz4 tank
sudo zfs set atime=off tank
```

The provisioning script creates the `tank/malmberg` dataset automatically; you only
need to create the pool. If ZFS is unavailable, the script creates a plain directory
at `/fs` instead and warns that backups require ZFS.

### 2. Install and provision

```bash
git clone https://github.com/lognd/malmberg
cd malmberg
uv sync

sudo uv run python -m malmberg_server setup
```

The script is idempotent: it is safe to re-run after a partial install or upgrade.
Re-running skips steps that are already complete (user exists, dataset exists,
cert present, cron jobs tagged).

**What the script does, in order:**

1. Validates the environment (platform, Python version, required commands).
   Exits with a clear error if any check fails.
2. Detects hardware; writes `/etc/malmberg/hardware.toml`.
3. Creates system user `malmberg` with no login shell (`useradd --system`).
4. Creates `/fs` (or the `--fs-root` path) owned by `malmberg:malmberg`, mode 750,
   with subdirectories `media/`, `uploads/`, `cloud/`, `.trash/`, `logs/`.
5. Creates ZFS dataset `tank/malmberg` and grants `malmberg` snapshot permissions.
   Skips gracefully if the dataset already exists or ZFS is unavailable.
6. Chowns `/etc/malmberg/` to the `malmberg` user.
7. Generates a self-signed TLS certificate pair at `/etc/malmberg/tls/`
   (4096-bit RSA, 10-year validity). Skips if the cert already exists.
8. Writes and enables `malmberg-server.service`.
9. Installs two idempotent cron jobs for the `malmberg` user:
   - **Trash purge** (03:15 daily): `find /fs/.trash -mtime +30 -delete`
   - **ZFS backup** (02:00 daily): triggers a ZFS snapshot via the backup module
   Each job is identified by a comment tag; re-running setup never duplicates them.
10. Generates a 6-digit pairing PIN and writes it to `/etc/malmberg/pairing-pin.txt`.
    If the file already exists with a valid PIN it is preserved.

**CLI options:**

```bash
sudo uv run python -m malmberg_server setup --help

  --fs-root DIR    Media filesystem root (default: /fs)
  --dry-run        Print what would be done without making changes
  --no-enable      Write the systemd unit but do not enable or start the service
```

### 3. Verify

```bash
systemctl status malmberg-server
curl http://localhost:8444/status
```

### Filesystem layout after provisioning

```
/fs/
  media/        -- photo and video store; date-partitioned as YYYY/MM/DD/
  uploads/      -- transient staging area; files move here before validation
  cloud/        -- per-provider download cache (iCloud, Google Photos, ...)
  .trash/       -- soft-deleted files; purged after 30 days by cron
  logs/         -- rolling log archive and media index
    media-index.jsonl   -- persistent media store (JSON-lines)
    backup-audit.jsonl  -- backup operation audit log

/etc/malmberg/
  hardware.toml       -- hardware profile (written by setup)
  pairing-pin.txt     -- 6-digit PIN shown to display operators
  tls/
    server.crt        -- self-signed TLS certificate
    server.key        -- private key (mode 600)
```

### TLS and pinning

The provisioning script generates a self-signed certificate. During pairing, the
display receives the server's certificate fingerprint and pins it. All subsequent
HTTPS connections from the display to the server verify against this pinned cert.
See [handshake.md](../design/handshake.md) for the full protocol.

To regenerate the certificate (e.g. after it expires):

```bash
sudo openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout /etc/malmberg/tls/server.key \
  -out /etc/malmberg/tls/server.crt \
  -days 3650 -subj "/CN=malmberg-server"
sudo systemctl restart malmberg-server
```

After regenerating, all paired displays must re-pair.

### Firewall

Open the required ports:

```bash
sudo ufw allow 8444/tcp   # server HTTP API
sudo ufw allow 9456/udp   # UDP discovery
```

---

## Display provisioning (Raspberry Pi)

Tested on: Pi Zero 2 W (Raspbian Bookworm), Pi 4, Pi 5.

### Prerequisites

- Raspbian Bookworm 64-bit (recommended)
- Python 3.10+ (included on Bookworm)
- `systemctl` available
- A display connected via HDMI or DSI; an active X session (or Wayland)
- `uv` installed

The setup script checks for `DISPLAY` / `WAYLAND_DISPLAY` and logs a notice if
neither is set. This is non-blocking: the systemd unit sets `DISPLAY=:0` itself, so
the check is informational only when running under sudo without a forwarded display.

### 1. Install

```bash
git clone https://github.com/lognd/malmberg
cd malmberg
uv sync --extra display
```

The `--extra display` flag installs `pygame`, `Pillow`, and `python-mpv`.

For reverse-geocoded location names in the overlay (optional):

```bash
uv sync --extra display --extra geocoding
```

Without `geopy`, GPS coordinates are shown as decimal degrees instead of a place name.

### 2. Provision

```bash
sudo uv run python -m malmberg_display setup
```

Runs as root; defaults the service user to `$SUDO_USER` (the person who ran sudo),
or `"pi"` if `$SUDO_USER` is not set. Override with `--user <name>`.

**What the script does, in order:**

1. Validates the environment (platform, Python version, `systemctl` present).
   DISPLAY/WAYLAND notices are warnings, not errors.
2. Detects hardware; writes `/etc/malmberg/hardware.toml`.
3. Writes `/etc/X11/xorg.conf.d/10-malmberg-no-blanking.conf` to disable screen
   blanking system-wide. If `/boot/firmware/config.txt` (or `/boot/config.txt`)
   exists, appends `consoleblank=0` to the Pi boot config.
4. Writes `~/.config/mpv/mpv.conf` for the service user:
   - `hwdec=auto` on profiles with `hw_video_decode=true` (Pi 4/5)
   - `hwdec=no` on profiles without it (Pi Zero 2 W, generic-x86)
5. If `profile.playwright_supported` is true and running interactively, offers to
   install playwright and download the Chromium browser (~500 MB). Skips silently
   in non-interactive runs and logs a warning with manual install instructions.
6. Writes `/etc/systemd/system/malmberg-display.service` with
   `Environment=DISPLAY=:0` and `Environment=XAUTHORITY=/home/<user>/.Xauthority`
   so the service can render to the physical screen without a logged-in session.
7. Enables the service (`systemctl enable`). Does not start it; the operator
   starts it manually after pairing.

**Pi Zero 2 W specifics:** the hardware detector automatically sets
`playwright_supported=false` and `max_preload_queue=2` to stay within the 512 MB
RAM limit. Verify these values if you see out-of-memory errors.

**CLI options:**

```bash
sudo uv run python -m malmberg_display setup --help

  --user USER    Username that owns the X session (default: $SUDO_USER or 'pi')
  --dry-run      Print what would be done without making changes
  --no-enable    Write the systemd unit but do not enable the service
```

### 3. Start and pair

```bash
sudo systemctl start malmberg-display
```

The display starts in discovery mode: it broadcasts a UDP datagram every 5 seconds
on port 9456 until it receives a response from a server. Enter the PIN shown on the
server to complete pairing. See [handshake.md](../design/handshake.md).

To skip discovery and connect directly to a known server URL:

```bash
# In ~/.config/malmberg/display.toml
server_url = "http://192.168.1.10:8444"
```

or pass `--server-url` on the command line.

---

## Running without systemd

For development or headless testing:

```bash
# Server
uv run python -m malmberg_server

# Server with a custom storage root
uv run python -m malmberg_server --fs-root /tmp/malmberg-test

# Display: local directory mode (no server needed)
uv run python -m malmberg_display --media-dir ~/Pictures

# Display: explicit server URL, no UDP discovery
uv run python -m malmberg_display --server-url http://192.168.1.10:8444

# Display: custom resolution
uv run python -m malmberg_display --width 1280 --height 720

# Display: disable overlays
uv run python -m malmberg_display --media-dir ~/Pictures
# or in display.toml:
# show_clock = false
# show_caption = false
```

Both roles also respond to `MALMBERG_*` environment variables; see
[configuration.md](../software/configuration.md).

---

## Re-running setup after an upgrade

Setup is fully idempotent. Each step checks whether it is already complete before
acting:

| Step | Idempotency mechanism |
|------|-----------------------|
| Hardware profile | Overwrites `hardware.toml` (detection may improve) |
| System user | `pwd.getpwnam` check; skips if user exists |
| Filesystem layout | `mkdir -p` with `exist_ok=True` |
| ZFS dataset | `zfs list` check; skips if dataset exists |
| TLS certificate | Checks for both `.crt` and `.key`; skips if both present |
| Systemd unit | Always overwrites (picks up new `ExecStart` path after `uv` upgrades) |
| Cron jobs | Comment-tag check (`# MALMBERG_TRASH_PURGE`, `# MALMBERG_ZFS_BACKUP`); skips if tag already in crontab |
| Pairing PIN | Preserves existing valid PIN; only generates a new one if absent or malformed |
