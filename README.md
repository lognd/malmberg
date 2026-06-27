# Malmberg

A self-hosted photo and video display system for the home. A low-power Linux
machine stores your media; one or more Raspberry Pi displays cycle through it
on screens around the house. Everything runs on your hardware, on your LAN,
with no cloud dependency.

```
[ Server (mini-PC / NUC) ]  <--LAN-->  [ Display (Raspberry Pi + screen) ]
  ZFS storage                              pygame slideshow
  HTTPS API                                cross-fade transitions
  EXIF ingest                              clock + photo metadata overlay
  Web dashboard                            automatic server discovery
```

## Features

- **Automatic pairing** -- displays find the server via UDP broadcast; a 6-digit
  PIN is the only manual step
- **EXIF-aware** -- date taken, GPS location (reverse-geocoded), and camera model
  shown as an overlay on each photo
- **Graceful offline mode** -- displays switch to a local cache when the server
  is unreachable and clearly say so
- **ZFS backups** -- probabilistic snapshot retention with a full audit log
- **Idempotent provisioning** -- `python -m malmberg_server setup` is safe to re-run
  after partial installs or upgrades
- **Hardware-adaptive** -- one codebase runs on Pi Zero 2 W through Pi 5 and
  generic x86; a HAL profile adjusts queue depth, mpv decode, and Chromium support

## Quick start

Run both roles on one machine to try it out -- no Pi, no ZFS required.

```bash
git clone https://github.com/lognd/malmberg
cd malmberg
uv sync

# terminal 1
uv run python -m malmberg_server --fs-root /tmp/malmberg-fs

# terminal 2
uv run python -m malmberg_display --media-dir ~/Pictures --width 1280 --height 720
```

Check `http://localhost:8444/status` (server) and `http://localhost:8443/status`
(display).

## Installation

```bash
uv sync                                          # base (server role)
uv sync --extra display                          # add pygame + mpv (display role)
uv sync --extra display --extra web-overlays     # add playwright clock/weather overlay
```

| Extra | What it adds |
|---|---|
| `display` | pygame, python-mpv -- required on display machines |
| `web-overlays` | playwright + Chromium -- optional clock/weather widget |
| `cloud-icloud` | pyicloud -- iCloud photo sync |
| `cloud-googlephotos` | google-auth -- Google Photos sync |

## Production setup

### Server (Ubuntu 22.04+)

```bash
sudo apt install zfsutils-linux   # optional but strongly recommended
sudo uv run python -m malmberg_server setup
```

Creates the `malmberg` system user, `/fs` directory layout, `tank/malmberg` ZFS
dataset, a self-signed TLS certificate, a systemd service, and two cron jobs
(trash purge + ZFS backup). Prints a 6-digit pairing PIN when done.

### Display (Raspberry Pi, Raspbian Bookworm)

```bash
uv sync --extra display
sudo uv run python -m malmberg_display setup
sudo systemctl start malmberg-display
```

Detects hardware, configures mpv, disables screen blanking, and writes the systemd
service. The service sets `DISPLAY=:0` so it renders to the physical screen without
a logged-in session.

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | Step-by-step walkthrough |
| [Configuration](docs/software/configuration.md) | All config fields for both roles |
| [API reference](docs/software/api-reference.md) | HTTP endpoints |
| [Module reference](docs/software/modules.md) | Python API |
| [Provisioning](docs/operations/provisioning.md) | Production setup in depth |
| [Troubleshooting](docs/operations/troubleshooting.md) | Common problems |
| [Design docs](docs/design/) | Architecture decisions and protocols |

## License

GPL v3 -- see [LICENSE](LICENSE). You are free to use, modify, and distribute
this software, including commercially, provided that derivative works are also
distributed under GPL v3.
