# Provisioning

This page covers production setup for both roles. For a quick single-machine test
see [Getting started](../getting-started.md).

---

## Server provisioning (Ubuntu 22.04+)

### Prerequisites

- Ubuntu 22.04 LTS or later (other distros work but are untested)
- Python 3.10+: `python3 --version`
- ZFS (strongly recommended):
  ```bash
  sudo apt install zfsutils-linux
  ```
- At least 8 GB RAM; mirrored storage for production
- `uv` installed for the `malmberg` user

### 1. Set up ZFS (recommended)

Create a mirrored pool and dataset before running the provisioning script. Replace
`/dev/sdb` and `/dev/sdc` with your actual drives:

```bash
sudo zpool create -o ashift=12 tank mirror /dev/sdb /dev/sdc
sudo zfs set compression=lz4 tank
sudo zfs set atime=off tank
sudo zfs create tank/malmberg
```

If ZFS is not available, the provisioning script creates a plain directory at `/fs`
instead. Backups (see [backup.md](../design/backup.md)) require ZFS.

### 2. Install and provision

```bash
git clone https://github.com/lognd/malmberg
cd malmberg
uv sync

sudo uv run python -m malmberg_server setup
```

The script is idempotent: it is safe to re-run after a partial install or upgrade.

**What the script does:**

1. Creates system user `malmberg` with no login shell
2. Creates `/fs` owned by `malmberg:malmberg`, mode 750
3. Sets ZFS dataset `tank/malmberg` mounted at `/fs` (skips if exists; creates plain
   dir if ZFS is unavailable)
4. Creates the standard directory layout under `/fs`
5. Generates a self-signed TLS certificate pair at `/etc/malmberg/tls/server.{crt,key}`
6. Writes `/etc/systemd/system/malmberg-server.service` and enables it
7. Grants `malmberg` user `zfs allow` permissions for snapshot operations
8. Prints a 6-digit pairing PIN to the console (or shows it on the status panel)

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
  .trash/       -- soft-deleted files; purged after trash_purge_days
  logs/         -- rolling log archive and media index
    media-index.jsonl   -- persistent media store (JSON-lines)
    backup-audit.jsonl  -- backup operation audit log
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
- A display connected via HDMI or DSI
- `uv` installed

### 1. Install

```bash
git clone https://github.com/lognd/malmberg
cd malmberg
uv sync --extra display
```

The `--extra display` flag installs `pygame`, `Pillow`, and `python-mpv`.

### 2. Provision

```bash
sudo uv run python -m malmberg_display setup
```

**What the script does:**

1. Detects hardware model and writes `~/.config/malmberg/hardware.toml`
2. Disables screen blanking: `xset s off`, `xset -dpms`
3. Configures mpv options appropriate for the detected hardware
4. Writes `/etc/systemd/system/malmberg-display.service`
5. Enables the service (does not start it yet)

**Pi Zero 2 W specifics:** the script automatically sets `playwright_supported=false`
and `max_preload_queue=2` in `hardware.toml` to stay within the 512 MB RAM limit.
If you have a Zero 2 W and see out-of-memory errors, verify these values.

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

# Display: local directory mode
uv run python -m malmberg_display --media-dir ~/Pictures

# Display: explicit server URL, no UDP discovery
uv run python -m malmberg_display --server-url http://192.168.1.10:8444

# Display: custom resolution
uv run python -m malmberg_display --width 1280 --height 720
```

Both roles also respond to `MALMBERG_*` environment variables; see
[configuration.md](../software/configuration.md).
