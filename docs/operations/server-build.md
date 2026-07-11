# Server build: ZFS-root mirror from scratch

This is the full, proven runbook for building a Malmberg file server with **both
disks mirrored -- OS, boot, and data** -- so any single drive can fail without
data loss or downtime. It is the procedure the reference server (`lars`) was
built with.

If you only need a plain single-disk server, skip to
[provisioning.md](provisioning.md); this page is for the mirrored production build.

> **Hardware assumed here:** a UEFI x86 mini-PC with **two identical disks**
> (the reference build used 2x 2 TB). The commands use stable
> `/dev/disk/by-id/...` names -- never `/dev/sdX`, which can change across reboots.
> Find yours with `ls -l /dev/disk/by-id/ | grep -v part`.

The build has four phases. Phases 1-2 are non-destructive to the running system;
phase 3 is the point of no return.

---

## Phase 0: Network and remote access

A fresh install often comes up with no DNS or default route, which blocks `apt`
and SSH. Fix networking first.

### DNS / gateway (netplan)

Symptom: `Temporary failure resolving 'archive.ubuntu.com'`, or `apt` hangs.

```bash
ip route | grep default        # is there a default route?
cat /etc/netplan/*.yaml         # what is configured?
```

A correct static config for one interface looks like this. **Keep exactly one
netplan file that owns the interface** -- two files each defining a default route
cause `Problem encountered while validating default route consistency`.

```yaml
# /etc/netplan/00-installer-config.yaml
network:
  version: 2
  ethernets:
    enp1s0:
      match:
        macaddress: aa:bb:cc:dd:ee:ff
      set-name: enp1s0
      dhcp4: false
      addresses: [192.168.69.69/22]
      routes:
        - to: default
          via: 192.168.68.1        # your router; must be inside the subnet
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
```

```bash
sudo netplan generate     # rejects a malformed file before it breaks the network
sudo netplan apply
ping -c2 archive.ubuntu.com
```

If a leftover `50-cloud-init.yaml` also configures the NIC, remove it and disable
cloud-init networking:

```bash
sudo mv /etc/netplan/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml.bak
echo 'network: {config: disabled}' | \
  sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
```

### SSH server

Symptom: `nmap` shows `22/tcp closed` (as opposed to `filtered`). `closed` means
the host is reachable but nothing is listening -- `sshd` is not running.

```bash
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
sudo ss -tlnp | grep :22        # confirm sshd is listening
```

For key-only root login (as the reference build uses), put the public key in
`/root/.ssh/authorized_keys` (mode 600, dir 700) and set
`PermitRootLogin prohibit-password` in `/etc/ssh/sshd_config`, then
`sudo systemctl restart ssh`.

---

## Phase 1: Build ZFS-root on the empty second disk

Nothing here touches the running OS disk. Install the boot tooling, partition the
empty disk, create the pools, copy the system in, and install the bootloader.

```bash
export DEBIAN_FRONTEND=noninteractive
sudo apt install -y zfs-initramfs gdisk dosfstools rsync

# Stable names -- SET THESE for your machine:
OSDISK=/dev/disk/by-id/ata-...WXB2D5334N4Y    # the disk currently running Ubuntu
NEWDISK=/dev/disk/by-id/ata-...WX12D83RFXK5   # the empty disk

# Partition NEWDISK: 1G EFI, 2G boot pool, rest root pool.
sudo sgdisk --zap-all "$NEWDISK"
sudo sgdisk -n1:1M:+1G -t1:EF00 -c1:EFI      "$NEWDISK"
sudo sgdisk -n2:0:+2G  -t2:BE00 -c2:bpool    "$NEWDISK"
sudo sgdisk -n3:0:0    -t3:BF00 -c3:tank     "$NEWDISK"
sudo partprobe "$NEWDISK"
```

Create the pools. `bpool` uses `compatibility=grub2` because GRUB reads `/boot`;
the root pool is named **`tank`** so `tank/malmberg` matches what the software
expects.

```bash
sudo zpool create -f -o ashift=12 -o autotrim=on -o compatibility=grub2 \
  -o cachefile=/etc/zfs/zpool.cache \
  -O devices=off -O acltype=posixacl -O xattr=sa \
  -O compression=lz4 -O normalization=formD -O relatime=on -O canmount=off \
  -O mountpoint=/boot -R /mnt bpool "${NEWDISK}-part2"

sudo zpool create -f -o ashift=12 -o autotrim=on \
  -O acltype=posixacl -O xattr=sa -O dnodesize=auto \
  -O compression=lz4 -O normalization=formD -O relatime=on -O canmount=off \
  -O mountpoint=/ -R /mnt tank "${NEWDISK}-part3"

sudo zfs create -o canmount=off -o mountpoint=none tank/ROOT
sudo zfs create -o canmount=noauto -o mountpoint=/ tank/ROOT/ubuntu
sudo zfs mount tank/ROOT/ubuntu
sudo zfs create -o canmount=off -o mountpoint=none bpool/BOOT
sudo zfs create -o mountpoint=/boot bpool/BOOT/ubuntu
sudo zpool set bootfs=tank/ROOT/ubuntu tank
sudo zfs create tank/malmberg
```

Copy the running system in (`-x` keeps rsync on the root filesystem):

```bash
sudo rsync -aHAXx --exclude=/swap.img --exclude='/tmp/*' \
  --exclude='/var/tmp/*' --exclude=/lost+found / /mnt/
```

Set up the ESP, fstab, and bootloader:

```bash
sudo mkfs.vfat -F32 -s1 -n EFI "${NEWDISK}-part1"
EFIUUID=$(sudo blkid -s UUID -o value "${NEWDISK}-part1")
sudo mkdir -p /mnt/boot/efi && sudo mount "${NEWDISK}-part1" /mnt/boot/efi

# fstab: / and /boot are mounted by ZFS; only the ESP goes here.
printf 'UUID=%s /boot/efi vfat umask=0077,shortname=winnt 0 1\n' "$EFIUUID" \
  | sudo tee /mnt/etc/fstab

sudo cp /etc/zfs/zpool.cache /mnt/etc/zfs/zpool.cache
sudo cp /etc/hostid /mnt/etc/hostid 2>/dev/null || sudo chroot /mnt zgenhostid -f

for d in proc sys dev dev/pts run; do sudo mount --rbind /$d /mnt/$d; done

sudo chroot /mnt /bin/bash -c '
  set -e
  echo RESUME=none > /etc/initramfs-tools/conf.d/resume
  systemctl enable zfs-import-cache zfs-import.target zfs-mount.service \
                   zfs-zed.service zfs.target
  update-initramfs -c -k all
  grub-install --target=x86_64-efi --efi-directory=/boot/efi \
               --bootloader-id=ubuntu-zfs --recheck --no-floppy
  update-grub
  grep -c tank/ROOT/ubuntu /boot/grub/grub.cfg   # must be > 0
'
```

Add a one-shot boot entry and a labelled fallback to the old system, then unmount:

```bash
NUM=$(efibootmgr | grep -i ubuntu-zfs | grep -oE 'Boot[0-9A-F]{4}' | head -1 | sed s/Boot//)
sudo efibootmgr -n "$NUM"     # BootNext: try ZFS once
# Explicit fallback to the still-intact old system on the OS disk:
sudo efibootmgr -c -d "$OSDISK" -p 1 -L "Ubuntu-OLD" -l '\EFI\ubuntu\shimx64.efi'

for m in $(mount | awk '{print $3}' | grep '^/mnt' | sort -r); do sudo umount -l "$m"; done
sudo zpool export bpool; sudo zpool export tank
```

---

## Phase 2: Reboot and verify (checkpoint)

**Be at the physical console for this reboot.** `BootNext` will try the ZFS system
once.

```bash
sudo systemctl reboot
```

- If it boots to the desktop, **verify you are on ZFS before continuing**:
  ```bash
  findmnt -no SOURCE,FSTYPE /        # tank/ROOT/ubuntu zfs
  findmnt -no SOURCE,FSTYPE /boot    # bpool/BOOT/ubuntu zfs
  zpool status                       # both pools ONLINE
  ```
- If it fails (grub rescue, panic, black screen): power-cycle, tap the firmware
  boot-menu key (usually **F12**), and pick **"Ubuntu-OLD"** to boot the untouched
  original system. Nothing is lost; diagnose and retry Phase 1.

Make ZFS the default and snapshot before the irreversible step:

```bash
sudo efibootmgr -o <zfs-entry>,<old-entry>,<others>
sudo zfs snapshot -r tank@pre-mirror
sudo zfs snapshot -r bpool@pre-mirror
```

---

## Phase 3: Absorb the old disk into the mirror (point of no return)

This wipes the original OS disk and attaches it as the mirror. Only do this after
Phase 2 succeeded.

```bash
# Clone the new disk's layout onto the old disk, with fresh GUIDs.
sudo sgdisk --zap-all "$OSDISK"
sudo sgdisk --replicate="$OSDISK" "$NEWDISK"
sudo sgdisk --randomize-guids "$OSDISK"
sudo partprobe "$OSDISK"

# Attach both pools -> 2-way mirrors (resilver starts automatically).
sudo zpool attach bpool "${NEWDISK}-part2" "${OSDISK}-part2"
sudo zpool attach tank  "${NEWDISK}-part3" "${OSDISK}-part3"

# Mirror the ESP so the old disk is independently bootable, and add its entry.
sudo mkfs.vfat -F32 -s1 -n EFI "${OSDISK}-part1"
sudo mkdir -p /mnt/efi && sudo mount "${OSDISK}-part1" /mnt/efi
sudo cp -a /boot/efi/EFI /mnt/efi/ && sudo umount /mnt/efi && sudo rmdir /mnt/efi
sudo efibootmgr -c -d "$OSDISK" -p 1 -L "Ubuntu-ZFS-sda" -l '\EFI\ubuntu-zfs\shimx64.efi'

sudo zpool status         # wait for "resilvered ... with 0 errors"; both ONLINE
```

---

## Phase 4: Provision the software

Clone to `/opt/malmberg` (a location the `malmberg` service user can execute --
**not** a home directory, which is mode 750 and blocks the service), then run
setup, which now also installs the mirror hardening and GitHub auto-update.

```bash
sudo apt install -y zfsutils-linux    # if not already present
# uv must be on PATH for root and the auto-updater:
sudo cp "$(command -v uv)" /usr/local/bin/uv

sudo git clone https://github.com/lognd/malmberg /opt/malmberg
cd /opt/malmberg && sudo uv sync
sudo chown -R malmberg:malmberg /opt/malmberg

sudo /opt/malmberg/.venv/bin/python -m malmberg_server setup
```

The setup run prints a summary and the pairing PIN. See
[provisioning.md](provisioning.md#what-the-script-does) for every step it performs,
including the ARC cap, monthly scrubs, EFI-mirror timer, and the auto-update timer.

---

## Verify the mirror actually protects data

Do not trust `zpool status` alone -- prove it by pulling a disk:

```bash
# Write known data.
sudo dd if=/dev/urandom of=/fs/test.bin bs=1M count=200
BEFORE=$(sha256sum /fs/test.bin | cut -d' ' -f1)

# Simulate a drive failure.
sudo zpool offline tank "${OSDISK}-part3"
sudo zpool status tank            # DEGRADED but ONLINE
echo 3 | sudo tee /proc/sys/vm/drop_caches
[ "$(sha256sum /fs/test.bin | cut -d' ' -f1)" = "$BEFORE" ] && echo "data survived"
echo test | sudo tee /fs/write-while-degraded.txt   # writes still work

# Restore and confirm a clean resilver.
sudo zpool online tank "${OSDISK}-part3"
sudo zpool status tank            # resilvered, both ONLINE, 0 errors
sudo rm /fs/test.bin /fs/write-while-degraded.txt
```

---

## Ongoing operation

- **Remote updates:** push to `main` on GitHub; the server pulls and redeploys
  within the update interval (default 10 min). See
  [upgrading.md](upgrading.md#unattended-github-updates). Never hand-edit
  `/opt/malmberg` -- the updater does `git reset --hard` and will discard it.
- **Replacing a failed disk:** see
  [troubleshooting.md](troubleshooting.md#a-mirror-disk-failed-or-shows-degraded).
- **Scrubs** run monthly automatically; **EFI** is re-mirrored daily.
