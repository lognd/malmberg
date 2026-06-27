# Getting started

This guide walks through installing Malmberg and getting a working server and display
on the same LAN. It assumes you are comfortable with a terminal but does not assume
familiarity with the codebase.

## Prerequisites

**Both machines:**
- Python 3.10 or later (`python3 --version`)
- `uv` package manager:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

**Server machine (Ubuntu 22.04+):**
- ZFS is optional for a quick-start test but strongly recommended for production:
  ```bash
  sudo apt install zfsutils-linux
  ```
- At least 8 GB RAM and mirrored storage for production use

**Display machine (Raspberry Pi):**
- Raspbian Bookworm (64-bit recommended)
- A display attached via HDMI or DSI

---

## 1. Install

Run this on **both** machines:

```bash
git clone https://github.com/lognd/malmberg
cd malmberg
uv sync
```

`uv sync` installs all base dependencies (FastAPI, uvicorn, Pillow, httpx, pydantic,
typani, and tomli on Python < 3.11) into a local `.venv/`.  You do not need to
activate the virtualenv; `uv run` handles it automatically.

**Display machine** — also install the hardware rendering extras:

```bash
uv sync --extra display       # pygame, python-mpv
```

**Optional extras** (install only what you need):

| Extra | Installs | When to use |
|---|---|---|
| `--extra display` | pygame, python-mpv | Any display machine |
| `--extra web-overlays` | playwright + Chromium | Clock/weather overlays (Pi 4/5 only) |
| `--extra cloud-icloud` | pyicloud | iCloud sync |
| `--extra cloud-googlephotos` | google-auth | Google Photos sync |
| `--extra all` | everything above | Development / testing |

Example — server with Google Photos sync:

```bash
uv sync --extra cloud-googlephotos
```

Example — display with all rendering options:

```bash
uv sync --extra display --extra web-overlays
```

---

## 2. Quick local test (single machine)

The fastest way to verify the system is to run both roles on one machine using a
local directory of photos. No pairing, no network, no hardware required.

```bash
# Terminal 1 -- server
uv run python -m malmberg_server --fs-root /tmp/malmberg-fs

# Terminal 2 -- display (local directory mode)
uv run python -m malmberg_display --media-dir ~/Pictures --width 1280 --height 720
```

Check that both are responding:
- Server status: `curl http://localhost:8444/status`
- Display status: `curl http://localhost:8443/status`

---

## 3. Provision the server

The provisioning script sets up the system user, filesystem layout, ZFS dataset,
TLS certificates, and systemd service in one step. It is safe to re-run.

```bash
sudo uv run python -m malmberg_server setup
```

What it does:
- Creates the `malmberg` system user with no login shell
- Creates `/fs` owned by `malmberg:malmberg`
- Creates ZFS dataset `tank/malmberg` mounted at `/fs` (skips if ZFS is unavailable)
- Generates a self-signed TLS certificate pair at `/etc/malmberg/tls/`
- Writes and enables `malmberg-server.service`
- Prints a pairing PIN to the console (or displays it on the status panel)

See [Provisioning](operations/provisioning.md) for the full filesystem layout and
manual configuration options.

---

## 4. Provision the display

On the Raspberry Pi:

```bash
sudo uv run python -m malmberg_display setup
```

What it does:
- Detects hardware and writes `~/.config/malmberg/hardware.toml`
- Disables screen blanking and DPMS
- Configures mpv for the detected hardware profile
- Writes and enables `malmberg-display.service`

For Pi Zero 2 W, the script automatically limits `max_preload_queue` to 2 and
disables `playwright_supported` to stay within the 512 MB RAM budget.

---

## 5. Pair server and display

Once both services are running:

1. The server generates a 6-digit PIN at startup and either prints it to the
   console or shows it on the status panel.
2. On the display, enter the PIN using the physical buttons or through the display
   web UI at `http://<display-ip>:8443/pair`.
3. The display sends its IP and the PIN over UDP broadcast; the server validates the
   PIN and completes the mutual TLS handshake.
4. Within a few seconds the display should begin cycling through photos.

If pairing does not complete, see [Troubleshooting](operations/troubleshooting.md#display-shows-searching-and-never-pairs).

---

## 6. Upload photos

**From a web browser:** navigate to `http://<server-ip>:8444/ui` and use the upload
form. Supports JPEG, PNG, HEIC, MP4, and MKV.

**From a USB drive:** plug the drive into the server. A udev rule triggers automatic
ingest: files are copied, deduplicated by SHA-256, EXIF-parsed, and moved to
`/fs/media/YYYY/MM/DD/`. The status panel shows progress.

**Via the API:** `POST /upload` with `multipart/form-data` — see the
[API reference](software/api-reference.md#post-upload).

---

## 7. What next?

- [Configuration reference](software/configuration.md) -- dwell time, fade duration,
  cache size, hide policy, and all other tunable settings
- [Operations guide](operations/provisioning.md) -- production TLS setup, ZFS
  configuration, backup retention
- [Dashboard design](design/dashboard.md) -- the HTMX web UI for managing media,
  displays, and cloud sources
- [API reference](software/api-reference.md) -- integrate with the server or display
  programmatically
