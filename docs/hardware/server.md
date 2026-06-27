# Server hardware

The server runs continuously, stores all your media, and serves it to displays
over your LAN. It does not need a screen or a keyboard after initial setup.

---

## What to get

### The machine

Any low-power x86 Linux machine works. The main requirements are:

- **Two drive bays** -- ZFS mirroring needs two identical drives. Single-drive
  setups work but you lose the safety net; a single drive failure destroys your
  photo library.
- **Enough RAM for ZFS** -- ZFS works best with at least 8 GB. It runs on 4 GB
  but will swap under load.
- **Gigabit Ethernet** -- transferring large photo libraries over Wi-Fi is slow
  and unreliable. Wire the server to your router.

Good options, roughly in order of value:

| Machine | RAM | Drive bays | Notes |
|---|---|---|---|
| Intel NUC (10th gen or later) | 8--64 GB | 1x M.2 + 1x 2.5" | Compact; needs a USB drive for the second ZFS leg unless you use a M.2 + SATA split |
| Beelink / Minisforum mini-PC | 16--32 GB | 2x M.2 or 1x M.2 + 1x 2.5" | Good value; quiet; widely available |
| Old laptop | 8+ GB | 1x internal + 1x USB | Works fine; battery acts as built-in UPS |
| Full tower desktop | 16+ GB | Many | Overkill but easy to expand |
| Raspberry Pi 5 (8 GB) | 8 GB | External USB only | Possible but slow for ZFS; not recommended for large libraries |

**What not to get for the server:**

- **Raspberry Pi 4 or earlier** -- too little RAM for ZFS to be comfortable on a
  real library. Fine for testing, not for production with thousands of photos.
- **Network-attached storage (NAS) boxes** -- most run proprietary firmware that
  makes running Python services awkward. Use a real Linux machine instead.
- **A machine with only one drive bay and no USB 3 ports** -- you need two legs
  for ZFS. USB 3 external drives are an acceptable second leg for home use.

### Storage drives

ZFS mirroring requires two identical drives. Buy the same model, same capacity.

**Recommended: 2x SSDs in a mirror.** SSDs are silent, fast, and reliable
enough for a photo library. 1--2 TB per drive covers most families.

| Use case | Recommended size (per drive) |
|---|---|
| Personal (< 50,000 photos) | 1 TB |
| Family with video (< 200,000 photos + video) | 2 TB |
| Multi-family or professional | 4 TB+ |

**What not to get for storage:**

- **SMR (shingled magnetic recording) hard drives** -- SMR drives have write
  performance that degrades severely under ZFS. Always check before buying.
  Safe HDD brands for ZFS: WD Red Plus, WD Gold, Seagate IronWolf (non-SMR).
  Avoid: WD Red (non-Plus), WD Green, Seagate Barracuda (most models).
- **USB 2 drives** -- too slow for anything beyond a small library.
- **SD cards** -- not suitable for primary ZFS storage; wear out quickly under
  write load.

### ZFS pool setup

Run this before provisioning. Replace `/dev/sdb` and `/dev/sdc` with your
actual drive paths (check with `lsblk`):

```bash
# Wipe existing partition tables (destructive -- double-check the paths)
sudo wipefs -a /dev/sdb /dev/sdc

# Create a mirrored pool
sudo zpool create \
  -o ashift=12 \
  -O compression=lz4 \
  -O atime=off \
  -O xattr=sa \
  tank mirror /dev/sdb /dev/sdc

# Verify
zpool status tank
zfs list
```

`ashift=12` is correct for all modern drives (4K sector alignment). Using
`ashift=9` on modern drives permanently degrades performance.

For M.2 NVMe drives use the `/dev/nvme0n1` style paths, not `/dev/sda`.

### Networking

- Wire the server to your router with a Cat 5e or better Ethernet cable.
- The server needs UDP port 9456 open for display discovery and TCP port 8444
  for the API. If your router has a firewall between LAN segments, open these.
- A static LAN IP or a DHCP reservation makes things simpler but is not required;
  displays that use UDP discovery will find the server regardless of its IP.

### Power

- Plug the server into a UPS (uninterruptible power supply) if you can. Sudden
  power loss mid-write is the most common cause of ZFS pool corruption. A basic
  UPS costs about the same as a drive and protects everything.
- The server draws 10--25 W at idle for a typical mini-PC with SSDs. Annual
  electricity cost is negligible.

---

## Minimum spec summary

| | Minimum | Recommended |
|---|---|---|
| CPU | Any x86-64, 2 cores | 4 cores |
| RAM | 4 GB | 8 GB+ |
| Storage | 2x 256 GB USB 3 SSD (mirror) | 2x 1 TB M.2 or 2.5" SSD (mirror) |
| Network | 100 Mbps Ethernet | Gigabit Ethernet |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS or 24.04 LTS |
