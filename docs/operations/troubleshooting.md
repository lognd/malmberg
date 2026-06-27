# Troubleshooting

---

## Display shows "SEARCHING..." and never pairs

The display broadcasts UDP on port 9456 and waits for a server response. Common
causes of failure:

1. **Different VLANs or subnets.** UDP broadcast traffic (`255.255.255.255`) does
   not cross router boundaries or VLAN boundaries on most managed switches. Both
   devices must be on the same Layer 2 segment.

2. **Server not running.**
   ```bash
   systemctl status malmberg-server
   curl http://<server-ip>:8444/
   ```

3. **Firewall blocking UDP.**
   ```bash
   sudo ufw status   # on the server
   # port 9456/udp must be open
   sudo ufw allow 9456/udp
   ```

4. **Wrong discovery port.** Both sides must use the same `discovery_port` (default
   `9456`). Check `~/.config/malmberg/display.toml` and
   `~/.config/malmberg/server.toml` on both machines.

**Quick fix:** bypass discovery entirely by setting `server_url` in
`display.toml` or using the `--server-url` flag:

```bash
uv run python -m malmberg_display --server-url http://192.168.1.10:8444
```

---

## Upload returns 409 Conflict

The file's SHA-256 digest already exists in the media store. This is deduplication
working as intended: the same photo or video will not be stored twice.

If you want to re-ingest the file with updated metadata, delete the existing item
first:

```bash
curl -X DELETE http://localhost:8444/media/<id>
```

Then re-upload.

---

## Upload returns 422 Unprocessable Entity

The server could not parse the file as a valid image or video. Causes:

- **Corrupted or truncated file.** Partial uploads (e.g. interrupted transfer) are
  the most common cause. Retry the upload from the source.
- **HEIC without libheif.** HEIC files require `libheif` installed on the server:
  ```bash
  sudo apt install libheif-dev
  pip install Pillow --force-reinstall   # recompile with libheif support
  ```
- **Unsupported raw format.** CR2, ARW, NEF, and other raw camera formats are not
  currently supported. Convert to JPEG or DNG before uploading.

---

## Display shows "OFFLINE MODE"

The display cannot reach the server. The offline cache continues to serve previously
downloaded media. The system will automatically leave offline mode and re-sync when
the server becomes reachable again; no manual action is required.

Common causes:
- Server is restarting or crashed (`systemctl status malmberg-server`)
- Network partition between server and display
- Server IP address changed due to DHCP reassignment -- assign the server a static
  IP or DHCP reservation to prevent this

The offline mode state is also visible in `GET /status` (`online: false`) and logged
at WARNING level with a timestamp.

---

## `extract_exif` returns `ExifError` for a file that looks valid

Pillow could not decode the file. This is separate from the file being a recognized
format -- the file must be a valid, non-truncated image that Pillow can open.

Steps to diagnose:

```python
from PIL import Image
img = Image.open("/path/to/file.jpg")
img.verify()   # raises on corruption
```

If `verify()` passes but `extract_exif` still returns `ExifError`, open a bug
report with the file type and error message from the server logs.

---

## Disk usage growing faster than expected

The `.trash/` directory accumulates soft-deleted files until the scheduled purge
runs (configurable via `trash_purge_days`, default 30 days).

Check current trash size:

```bash
du -sh /fs/.trash/
```

To purge immediately (manual step until `POST /admin/purge-trash` is implemented):

```bash
rm -rf /fs/.trash/*
```

Also check the `cloud/` directory -- cloud provider caches can grow large if the
cleanup job is not running.

---

## `uv run pytest` fails with `ImportError: No module named 'pygame'`

`pygame` is an optional extra not installed in the default dev environment
(`uv sync --dev`). The automated test suite (`tests/unit/`, `tests/integration/`,
`tests/system/`) never imports pygame directly.

If you are seeing this error, something is importing `display/picture.py` or
`display/video.py` at collection time from a test that should not. Check:

- Is the failing test in `tests/manual/`? Manual tests are excluded from pytest's
  `testpaths` setting and should not appear in the automated suite.
- Does a test import `from malmberg_display.slideshow.producers import ...` at
  module level? The producers `__init__.py` imports `ServerProducer` and
  `CacheProducer`, which in turn import from `server.py`. Check that this chain
  does not reach `picture.py` directly.

To install pygame for local testing:

```bash
uv sync --extra display
```

---

## HAL detection returns `generic-x86` on a Raspberry Pi

The `get_hardware_profile()` function reads `hardware.toml`. If the provisioning
script has not been run, the file does not exist and the system falls back to the
generic-x86 profile.

Create the file manually:

```toml
# ~/.config/malmberg/hardware.toml
name = "pi-4"
hw_video_decode = true
gpio_available = true
status_panel_bus = "none"
max_preload_queue = 4
playwright_supported = true
```

Adjust values for your specific board. See
[configuration.md](../software/configuration.md#hardware-profile) for all fields.

---

## ZFS snapshot fails with `permission denied`

The server process runs as the `malmberg` user, which needs explicit ZFS permissions
on the dataset:

```bash
sudo zfs allow malmberg snapshot,destroy,send tank/malmberg
```

Verify the permissions are in place:

```bash
zfs allow tank/malmberg
```

---

## Slideshow stops advancing after pausing

`POST /slideshow/pause` toggles the pause state. If the display is paused and the
`next` button is pressed, the pause is cleared and the next item is served. If the
display appears stuck but not paused, check that:

- The producer queue is not empty (`queue_depth` in `GET /status`)
- The server is still reachable if using `ServerProducer`
- The cache directory is not full (the download in `_download()` fails silently and
  skips the item if disk is full)

---

## Logs and diagnostics

Both roles write structured logs to stdout (DEBUG/INFO) and stderr (WARNING+).
When running under systemd:

```bash
journalctl -u malmberg-server -f     # live server logs
journalctl -u malmberg-display -f    # live display logs
journalctl -u malmberg-server --since "1 hour ago"   # recent history
```

The media index is a plain text file readable with any editor:

```bash
cat /fs/logs/media-index.jsonl | python3 -m json.tool | head -40
```

The backup audit log:

```bash
cat /fs/logs/backup-audit.jsonl | python3 -m json.tool
```
