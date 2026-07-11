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
  tolerated up to a point (`ImageFile.LOAD_TRUNCATED_IMAGES` is enabled), but a
  file cut off before its headers finish will still fail. Retry the upload from
  the source.
- **pillow-heif failed to load.** HEIC/HEIF/AVIF decoding (the default iPhone
  photo format) is provided by the `pillow-heif` dependency, registered as a
  Pillow plugin at import time in both `malmberg_server.ingest.media` and
  `malmberg_display.display.picture`. This is best-effort: if `pillow-heif`
  cannot be imported on a given platform, a warning is logged at startup and
  HEIC/HEIF/AVIF files fail to decode (422) instead of crashing ingest. Check
  server logs for `pillow-heif unavailable` and reinstall if needed:
  ```bash
  uv pip install --force-reinstall pillow-heif
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
on the dataset. `setup` grants these automatically on every run, but to do it by
hand:

```bash
sudo zfs allow malmberg snapshot,destroy,mount,hold tank/malmberg
```

Verify the permissions are in place:

```bash
zfs allow tank/malmberg
```

---

## `cannot create 'tank/malmberg': no such pool 'tank'`

`setup` creates the *dataset* `tank/malmberg`, but it never creates the *pool* --
that means formatting disks, which must be a deliberate manual step. The error
means the `tank` pool does not exist yet.

`tank` is the pool; `tank/malmberg` is a dataset inside it. Pools are made with
`zpool` (not `zfs`). Find your disks and create the pool first:

```bash
sudo zpool list                                   # confirm 'tank' is absent
lsblk -dpno NAME,SIZE,FSTYPE,MODEL                # find the data disks
ls -l /dev/disk/by-id/ | grep -v part             # stable names to use

# Two-disk mirror (recommended). USE by-id NAMES, not /dev/sdX:
sudo zpool create -o ashift=12 tank mirror \
  /dev/disk/by-id/<diskA> /dev/disk/by-id/<diskB>
```

Then re-run `setup` (idempotent) -- it finds the pool and creates the dataset.
For a full mirrored **OS + data** build, follow [server-build.md](server-build.md)
instead.

> `zpool create` erases the target disks. Double-check you are not naming the OS
> disk (the one with the mounted `/`, `/boot`, or `/boot/efi` partitions).

---

## A mirror disk failed, or a pool shows DEGRADED

`zpool status` shows a member as `FAULTED`, `DEGRADED`, `UNAVAIL`, or `OFFLINE`.
The pool keeps serving data from the surviving disk; replace the bad one:

```bash
zpool status -v                                   # identify the failed by-id device
# Physically swap the disk, then partition the replacement like the survivor:
GOOD=/dev/disk/by-id/<surviving-disk>
NEW=/dev/disk/by-id/<replacement-disk>
sudo sgdisk --replicate="$NEW" "$GOOD"
sudo sgdisk --randomize-guids "$NEW"

# Replace in both pools (partitions 2 = bpool, 3 = tank on the standard layout):
sudo zpool replace bpool <old-id-part2> "${NEW}-part2"
sudo zpool replace tank  <old-id-part3> "${NEW}-part3"

# Restore the bootloader onto the new disk so it can boot alone:
sudo mkfs.vfat -F32 -s1 -n EFI "${NEW}-part1"
sudo /usr/local/sbin/malmberg-sync-esp.sh         # installed by setup
sudo efibootmgr -c -d "$NEW" -p 1 -L "Ubuntu-ZFS-new" -l '\EFI\ubuntu-zfs\shimx64.efi'

sudo zpool status                                 # wait for resilver, 0 errors
```

To prove redundancy without a real failure, see the drive-pull test in
[server-build.md](server-build.md#verify-the-mirror-actually-protects-data).

---

## Machine will not boot / drops to `grub rescue` after a disk change

Each disk in the mirror carries its own EFI System Partition and UEFI boot entry
(`Ubuntu` and `Ubuntu-ZFS-sda`). `setup` installs a daily timer
(`malmberg-sync-esp.timer`) that mirrors `/boot/efi` to the other disk so both stay
bootable.

- At the firmware boot menu (usually **F12**), pick the entry for the disk that is
  still healthy.
- List/repair entries from a booted system:
  ```bash
  efibootmgr                       # view entries and BootOrder
  sudo /usr/local/sbin/malmberg-sync-esp.sh    # re-mirror the ESP now
  ```
- If GRUB itself is damaged on one disk, reinstall it while booted from the good
  disk (ESP mounted at `/boot/efi`):
  ```bash
  sudo grub-install --target=x86_64-efi --efi-directory=/boot/efi \
    --bootloader-id=ubuntu-zfs --recheck
  sudo update-grub
  ```

---

## Server is sluggish / high memory pressure with ZFS

The ZFS ARC (adaptive cache) defaults to half of RAM but can still crowd services
on a small box. `setup` writes an ARC cap to `/etc/modprobe.d/zfs.conf`
(`zfs_arc_max`, ~half of RAM). To change it:

```bash
cat /etc/modprobe.d/zfs.conf
echo 3221225472 | sudo tee /sys/module/zfs/parameters/zfs_arc_max   # live, 3 GiB
# Persist by editing zfs.conf and rebuilding the initramfs:
sudo update-initramfs -u
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

## `apt` fails: `Temporary failure resolving 'archive.ubuntu.com'`

DNS is not working. Determine whether it is DNS-only or no internet at all:

```bash
ping -c2 8.8.8.8        # raw IP works => routing OK, DNS broken
ping -c2 google.com     # name fails    => confirms DNS
ip route | grep default # is there a default gateway at all?
```

- **IP works, name fails (DNS only):** quick fix
  `echo "nameserver 1.1.1.1" | sudo tee /etc/resolv.conf` (temporary). Permanent
  fix: add `nameservers: {addresses: [1.1.1.1, 8.8.8.8]}` under the interface in
  `/etc/netplan/*.yaml`, then `sudo netplan apply`.
- **No default route:** the static config is missing a gateway; add a
  `routes: [{to: default, via: <router-ip>}]` block. See
  [server-build.md](server-build.md#dns--gateway-netplan).

### netplan: `default route consistency` / `gateway4 has been deprecated`

Two netplan files both define networking for the interface (commonly a leftover
`50-cloud-init.yaml` alongside `00-installer-config.yaml`). Keep exactly one:

```bash
ls -la /etc/netplan/
grep -rn "gateway4\|routes\|addresses" /etc/netplan/
sudo mv /etc/netplan/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml.bak
sudo netplan generate && sudo netplan apply
```

Use the modern `routes:` syntax, not the deprecated `gateway4:`.

---

## Cannot SSH to the server: `nmap` shows `22/tcp closed`

`closed` (host replies, nothing listening) is different from `filtered` (firewall
drops the packet):

- **`closed`** -- the SSH daemon is not running. Opening ports/adding a key does not
  start it:
  ```bash
  sudo apt install -y openssh-server
  sudo systemctl enable --now ssh
  sudo ss -tlnp | grep :22        # confirm sshd is listening
  ```
- **`filtered`** -- a firewall/port-forward is blocking it. Check `ufw`/router rules.

If SSH connects but the key is rejected, confirm the *exact* public key is in the
right file for the login user (`/root/.ssh/authorized_keys` for root; dir `700`,
file `600`, one unbroken line), and that `PermitRootLogin` allows key auth. A
hand-typed key with one wrong character fails silently -- verify with `ssh -v`.

---

## Server auto-start and power behavior

The `malmberg-server` service is enabled (`systemctl is-enabled malmberg-server`),
so it starts at boot with no login required, and `/fs` auto-mounts via
`zfs-import-cache`/`zfs-mount`. If it does *not* come up on its own:

```bash
systemctl is-enabled malmberg-server zfs-import-cache zfs-mount   # all "enabled"
sudo systemctl enable malmberg-server                            # if not
journalctl -u malmberg-server -b                                 # boot-time errors
```

To have the machine **power on automatically after a mains outage**, enable
"Restore on AC Power Loss" -> Power On in the UEFI/BIOS setup -- this is a firmware
setting and cannot be configured from the OS.

For a headless server you can drop the desktop to free RAM (auto-start and SSH are
unaffected):

```bash
sudo systemctl set-default multi-user.target
```

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
