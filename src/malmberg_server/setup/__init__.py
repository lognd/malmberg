"""Idempotent provisioning for the Malmberg server role.

Invoked as::

    sudo python -m malmberg_server setup [--fs-root /fs] [--dry-run] [--no-enable]

Every step is idempotent: it is safe to re-run after a partial install or
after an upgrade.  Steps that cannot be completed non-fatally (e.g. ZFS
unavailable) emit a warning and continue.

Beyond the base install it also hardens a mirrored-ZFS deployment and wires up
unattended updates:

* grants the service user snapshot rights on the data dataset,
* caps the ZFS ARC to roughly half of RAM,
* enables monthly scrubs on every imported pool,
* mirrors the EFI System Partition to every other disk backing the root pool
  (so any single disk in the mirror can boot the machine alone), and
* installs a systemd timer that pulls the latest code from GitHub and redeploys.

Exit codes:
  0  All required steps completed (warnings may have been emitted).
  1  A required step failed (details printed to stderr).
  2  Not running as root.
"""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import random
import subprocess
import sys
from pathlib import Path

from malmberg_core.hal.detect import _detect_profile, write_hardware_toml
from malmberg_core.hal.profile import HardwareProfile
from malmberg_core.logging import get_logger
from malmberg_core.provision import (
    DEFAULT_BRANCH,
    DEFAULT_REPO_DIR,
    DEFAULT_UPDATE_MINUTES,
    detect_repo_dir,
    install_github_autoupdate,
)
from malmberg_core.provision import (
    has_cmd as _has_cmd,
)
from malmberg_core.provision import (
    write_executable as _write_executable,
)

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Platform validation
# ---------------------------------------------------------------------------

_MIN_PYTHON = (3, 10)
_REQUIRED_CMDS = ("systemctl", "useradd")
_OPTIONAL_CMDS = ("openssl",)
_ZFS_INSTALL_HINT = (
    "OpenZFS not found. Install with: sudo apt install zfsutils-linux\n"
    "  Snapshots and backup retention will be unavailable until ZFS is set up.\n"
    "  After installing, re-run setup so the ZFS dataset is created."
)


def validate_environment() -> list[str]:
    """Return a list of blocking problems found in the current environment.

    Each entry is a human-readable sentence describing one problem.  An empty
    list means the environment is suitable for provisioning.
    """
    problems: list[str] = []

    if sys.platform != "linux":
        problems.append(
            f"Unsupported platform '{sys.platform}'; malmberg-server requires Linux."
        )

    if sys.version_info < _MIN_PYTHON:
        v = ".".join(str(x) for x in sys.version_info[:2])
        req = ".".join(str(x) for x in _MIN_PYTHON)
        problems.append(f"Python {req}+ required; found {v}.")

    for cmd in _REQUIRED_CMDS:
        if not _has_cmd(cmd):
            problems.append(
                f"Required command '{cmd}' not found. "
                "Install it with: sudo apt install systemd passwd"
            )

    if not _has_cmd("zfs"):
        _log.warning(_ZFS_INSTALL_HINT)

    return problems


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SYSTEM_USER = "malmberg"
_CONFIG_DIR = Path("/etc/malmberg")
_TLS_DIR = _CONFIG_DIR / "tls"
_HARDWARE_TOML = _CONFIG_DIR / "hardware.toml"
_PIN_FILE = _CONFIG_DIR / "pairing-pin.txt"
_SYSTEMD_UNIT = Path("/etc/systemd/system/malmberg-server.service")

# Single home for the ZFS names so pool/dataset are never duplicated inline.
_ZFS_POOL = "tank"
_ZFS_DATASET = f"{_ZFS_POOL}/malmberg"
_ZFS_USER_PERMS = "snapshot,destroy,mount,hold"
_ARC_CONF = Path("/etc/modprobe.d/zfs.conf")

_FS_SUBDIRS = ("media", "uploads", "cloud", ".trash", "logs")

# ufw rules to open when a firewall is present: (port, protocol, comment).
# 8444/tcp is the server API; 9456/udp is display discovery.
_FIREWALL_RULES = (
    ("8444", "tcp", "malmberg server API"),
    ("9456", "udp", "malmberg UDP discovery"),
)

# Unattended GitHub updates live in malmberg_core.provision (shared with display).

# EFI mirror (keep every disk in the pool independently bootable).
_ESP_SYNC_SCRIPT = Path("/usr/local/sbin/malmberg-sync-esp.sh")
_ESP_SYNC_SERVICE = Path("/etc/systemd/system/malmberg-sync-esp.service")
_ESP_SYNC_TIMER = Path("/etc/systemd/system/malmberg-sync-esp.timer")

_UNIT_TEMPLATE = """\
[Unit]
Description=Malmberg File Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={work_dir}
ExecStart={python} -m malmberg_server
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""

# GUID that marks an EFI System Partition (constant across all GPT disks).
_ESP_TYPE_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"

_ESP_SYNC_SCRIPT_BODY = """\
#!/bin/bash
# Managed by `malmberg_server setup` -- edits are overwritten on the next run.
# Mirrors the mounted EFI System Partition onto the ESP of every OTHER disk
# backing the ZFS pools, so any single disk can boot the machine alone.
set -euo pipefail
SRC_MNT=/boot/efi
SRC_DEV=$(findmnt -no SOURCE "$SRC_MNT")
SRC_DISK=/dev/$(lsblk -no PKNAME "$SRC_DEV")
mapfile -t POOL_DISKS < <(zpool status -PL | grep -oE '/dev/[a-z]+' | sort -u)
for disk in "${{POOL_DISKS[@]}}"; do
    [ "$disk" = "$SRC_DISK" ] && continue
    part=$(lsblk -rno NAME,PARTTYPE "$disk" \
        | awk 'tolower($2)=="{esp_guid}"{{print "/dev/"$1; exit}}')
    [ -z "$part" ] && continue
    m=$(mktemp -d)
    mount "$part" "$m"
    rsync -a --delete "$SRC_MNT"/ "$m"/
    umount "$m"; rmdir "$m"
    logger -t malmberg-sync-esp "mirrored ESP $SRC_DEV -> $part"
done
"""

_ESP_SYNC_SERVICE_BODY = """\
[Unit]
Description=Mirror the EFI System Partition to every other pool disk

[Service]
Type=oneshot
ExecStart={script}
"""

_ESP_SYNC_TIMER_BODY = """\
[Unit]
Description=Daily EFI mirror to secondary pool disks

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> None:
    """Run all provisioning steps.  Prints a summary on completion."""
    dry = getattr(args, "dry_run", False)
    no_enable = getattr(args, "no_enable", False)
    no_hardening = getattr(args, "no_hardening", False)
    fs_root = Path(getattr(args, "fs_root", None) or "/fs")

    _require_root()

    # Platform and environment validation (blocking).
    problems = validate_environment()
    if problems:
        _log.error("Cannot provision: environment checks failed.")
        for p in problems:
            _log.error("  - %s", p)
        sys.exit(1)

    steps: list[tuple[str, str]] = []
    warnings: list[str] = []

    # 1. Hardware profile
    profile = _step_hardware(dry, warnings)
    steps.append(("Hardware profile", f"{_HARDWARE_TOML} ({profile.name})"))

    # 2. System user
    _step_user(dry)
    steps.append(("System user", f"'{_SYSTEM_USER}' present (no login shell)"))

    # 3. Filesystem layout
    _step_dirs(fs_root, dry)
    steps.append(("Filesystem layout", str(fs_root)))

    # 4. ZFS dataset
    zfs_msg = _step_zfs(fs_root, dry, warnings)
    steps.append(("ZFS", zfs_msg))

    # 4b. ZFS delegated permissions (always, even when the dataset pre-existed)
    steps.append(("ZFS permissions", _step_zfs_permissions(dry, warnings)))

    # 5. Config directory ownership
    _step_config_ownership(dry)
    steps.append(("Config dir", str(_CONFIG_DIR)))

    # 6. TLS certificate
    _step_tls(dry, warnings)
    steps.append(("TLS certificate", str(_TLS_DIR / "server.crt")))

    # 7. Systemd unit
    _step_unit(fs_root, dry)
    steps.append(("Systemd unit", str(_SYSTEMD_UNIT)))

    # 8. Enable / start service
    if not no_enable:
        _step_enable(dry, warnings)
        steps.append(("Service", "malmberg-server enabled and started"))
    else:
        steps.append(("Service", "skipped (--no-enable)"))

    # 8b. Firewall: open API + discovery ports so displays can reach the server.
    steps.append(("Firewall", _step_firewall(dry, warnings)))

    # 9. Cron jobs (trash purge + ZFS backup)
    _step_cron(fs_root, dry, warnings)
    steps.append(("Cron jobs", "trash purge + ZFS backup installed"))

    # 10. Mirror hardening (ARC cap, scrubs, EFI mirror)
    if no_hardening:
        steps.append(("Mirror hardening", "skipped (--no-hardening)"))
    else:
        steps.append(("ARC limit", _step_arc_limit(dry, warnings)))
        steps.append(("ZFS scrubs", _step_scrubs(dry, warnings)))
        steps.append(("EFI mirror", _step_esp_mirror(dry, warnings)))

    # 11. Unattended GitHub updates
    steps.append(("Auto-update", _step_auto_update(args, dry, warnings)))

    # 12. Pairing PIN
    pin = _step_pin(dry)
    steps.append(("Pairing PIN", pin))

    _print_summary(steps, warnings, pin)


# ---------------------------------------------------------------------------
# Individual steps
# ---------------------------------------------------------------------------


def _step_hardware(dry: bool, warnings: list[str]) -> HardwareProfile:
    result = _detect_profile()
    if result.is_ok:
        profile = result.danger_ok
    else:
        profile = HardwareProfile.fallback()
        warnings.append(
            "Hardware auto-detection failed; using generic-x86 fallback profile. "
            f"Edit {_HARDWARE_TOML} manually if needed. (Expected on non-Pi hardware.)"
        )
    if not dry:
        write_hardware_toml(profile, _HARDWARE_TOML)
    _log.info("Hardware profile: %s", profile.name)
    return profile


def _step_user(dry: bool) -> None:
    try:
        pwd.getpwnam(_SYSTEM_USER)
        _log.info("System user '%s' already exists.", _SYSTEM_USER)
        return
    except KeyError:
        pass
    _log.info("Creating system user '%s'.", _SYSTEM_USER)
    if not dry:
        subprocess.run(
            [
                "useradd",
                "--system",
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
                _SYSTEM_USER,
            ],
            check=True,
        )


def _step_dirs(fs_root: Path, dry: bool) -> None:
    _log.info("Ensuring filesystem layout under %s.", fs_root)
    if dry:
        return
    try:
        uid = pwd.getpwnam(_SYSTEM_USER).pw_uid
        gid = grp.getgrnam(_SYSTEM_USER).gr_gid
    except KeyError:
        # Dry-run or user not yet created; use current uid/gid.
        uid = os.getuid()
        gid = os.getgid()

    fs_root.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(fs_root, uid, gid)
    for sub in _FS_SUBDIRS:
        d = fs_root / sub
        d.mkdir(mode=0o750, exist_ok=True)
        os.chown(d, uid, gid)


def _step_zfs(fs_root: Path, dry: bool, warnings: list[str]) -> str:
    """Create the ZFS dataset if ZFS is available; otherwise warn."""
    if not _has_cmd("zfs"):
        warnings.append(
            "ZFS not found.  Install with `sudo apt install zfsutils-linux` "
            "for snapshot-based backups.  Plain directory in use."
        )
        return "ZFS unavailable -- using plain directory"

    if _zfs_dataset_exists(_ZFS_DATASET):
        _log.info("ZFS dataset '%s' already exists.", _ZFS_DATASET)
        return f"{_ZFS_DATASET} (already exists)"

    _log.info("Creating ZFS dataset '%s'.", _ZFS_DATASET)
    if not dry:
        result = subprocess.run(
            ["zfs", "create", _ZFS_DATASET],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            warnings.append(
                f"Could not create ZFS dataset '{_ZFS_DATASET}': "
                f"{result.stderr.strip()}. Create the pool first, e.g. "
                f"`sudo zpool create {_ZFS_POOL} mirror <diskA> <diskB>`, "
                f"then re-run setup."
            )
            return f"{_ZFS_DATASET} -- creation failed (see warnings)"

    return f"{_ZFS_DATASET} created"


def _step_zfs_permissions(dry: bool, warnings: list[str]) -> str:
    """Grant the service user snapshot rights on the data dataset (idempotent)."""
    if not _has_cmd("zfs"):
        return "skipped (ZFS unavailable)"
    if not _zfs_dataset_exists(_ZFS_DATASET):
        return f"skipped ({_ZFS_DATASET} absent)"
    _log.info("Granting '%s' [%s] on %s.", _SYSTEM_USER, _ZFS_USER_PERMS, _ZFS_DATASET)
    if not dry:
        subprocess.run(
            ["zfs", "allow", _SYSTEM_USER, _ZFS_USER_PERMS, _ZFS_DATASET],
            check=False,
        )
    return f"{_SYSTEM_USER} may [{_ZFS_USER_PERMS}] {_ZFS_DATASET}"


def _step_config_ownership(dry: bool) -> None:
    if dry:
        return
    try:
        uid = pwd.getpwnam(_SYSTEM_USER).pw_uid
        gid = grp.getgrnam(_SYSTEM_USER).gr_gid
    except KeyError:
        return
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chown(_CONFIG_DIR, uid, gid)


def _step_tls(dry: bool, warnings: list[str]) -> None:
    cert = _TLS_DIR / "server.crt"
    key = _TLS_DIR / "server.key"

    if cert.is_file() and key.is_file():
        _log.info("TLS certificate already present at %s.", cert)
        return

    if not _has_cmd("openssl"):
        warnings.append(
            "openssl not found.  Install with `sudo apt install openssl` and "
            f"regenerate the certificate manually (see provisioning.md). "
            f"Expected paths: {cert}, {key}"
        )
        return

    _log.info("Generating self-signed TLS certificate at %s.", cert)
    if dry:
        return

    _TLS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:4096",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "3650",
            "-subj",
            "/CN=malmberg-server",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        warnings.append(
            f"openssl certificate generation failed: {result.stderr.strip()}"
        )
        return
    key.chmod(0o600)
    _log.info("TLS certificate written.")


def _step_unit(fs_root: Path, dry: bool) -> None:
    content = _UNIT_TEMPLATE.format(
        user=_SYSTEM_USER,
        work_dir=str(fs_root),
        python=sys.executable,
    )
    _log.info("Writing systemd unit to %s.", _SYSTEMD_UNIT)
    if dry:
        return
    _SYSTEMD_UNIT.write_text(content)
    subprocess.run(["systemctl", "daemon-reload"], check=False)


def _step_enable(dry: bool, warnings: list[str]) -> None:
    _log.info("Enabling and starting malmberg-server service.")
    if dry:
        return
    result = subprocess.run(
        ["systemctl", "enable", "--now", "malmberg-server"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        warnings.append(
            f"systemctl enable failed: {result.stderr.strip()}. "
            "Start manually: sudo systemctl start malmberg-server"
        )


def _step_firewall(dry: bool, warnings: list[str]) -> str:
    """Open the API and discovery ports if ufw is present (idempotent)."""
    if not _has_cmd("ufw"):
        return "skipped (ufw not installed)"
    opened: list[str] = []
    for port, proto, comment in _FIREWALL_RULES:
        _log.info("Allowing %s/%s through ufw.", port, proto)
        if not dry:
            subprocess.run(
                ["ufw", "allow", f"{port}/{proto}", "comment", comment],
                check=False,
                capture_output=True,
            )
        opened.append(f"{port}/{proto}")
    if not dry:
        subprocess.run(["ufw", "reload"], check=False, capture_output=True)
    return "opened " + ", ".join(opened)


def _step_cron(fs_root: Path, dry: bool, warnings: list[str]) -> None:
    """Install idempotent cron jobs for trash purge and ZFS backup.

    Each job is identified by a unique comment tag so re-running setup
    never duplicates entries.
    """
    jobs = [
        (
            "MALMBERG_TRASH_PURGE",
            # Run at 03:15 daily; purge .trash files older than 30 days.
            f"15 3 * * * find {fs_root}/.trash -mtime +30 -delete",
        ),
        (
            "MALMBERG_ZFS_BACKUP",
            # Run at 02:00 daily; trigger a ZFS snapshot via the server API.
            f"0 2 * * * {sys.executable} -c "
            f'"from malmberg_server.backup.zfs import snapshot; '
            f"snapshot('{_ZFS_DATASET}')\"",
        ),
    ]

    if not _has_cmd("crontab"):
        warnings.append(
            "crontab not found; cron jobs not installed. "
            "Install with: sudo apt install cron"
        )
        return

    # Read the current crontab for the malmberg user (or root if user absent).
    read_result = subprocess.run(
        ["crontab", "-u", _SYSTEM_USER, "-l"],
        capture_output=True,
        text=True,
    )
    existing = read_result.stdout if read_result.returncode == 0 else ""

    new_entries: list[str] = []
    for tag, job_line in jobs:
        if tag in existing:
            _log.info("Cron job '%s' already present; skipping.", tag)
            continue
        new_entries.append(f"# {tag}\n{job_line}")

    if not new_entries:
        return

    updated = existing.rstrip("\n") + "\n" + "\n".join(new_entries) + "\n"
    _log.info("Installing %d new cron job(s).", len(new_entries))
    if dry:
        return

    proc = subprocess.run(
        ["crontab", "-u", _SYSTEM_USER, "-"],
        input=updated,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        warnings.append(
            f"crontab install failed: {proc.stderr.strip()}. "
            "Install cron jobs manually (see provisioning.md)."
        )


def _step_arc_limit(dry: bool, warnings: list[str]) -> str:
    """Cap the ZFS ARC at roughly half of RAM so services stay responsive."""
    if not _has_cmd("zfs"):
        return "skipped (ZFS unavailable)"
    total = _mem_total_bytes()
    if total is None:
        return "skipped (RAM unknown)"
    arc_max = max(1 * 1024**3, total // 2)
    content = (
        "# Managed by malmberg_server setup: cap ARC at ~half of RAM.\n"
        f"options zfs zfs_arc_max={arc_max}\n"
    )
    if not dry:
        if not _ARC_CONF.is_file() or _ARC_CONF.read_text() != content:
            _ARC_CONF.write_text(content)
            subprocess.run(["update-initramfs", "-u"], check=False, capture_output=True)
        # Apply immediately when the module is already loaded.
        live = Path("/sys/module/zfs/parameters/zfs_arc_max")
        try:
            live.write_text(str(arc_max))
        except OSError:
            pass
    return f"{arc_max / 1024**3:.1f} GiB max"


def _step_scrubs(dry: bool, warnings: list[str]) -> str:
    """Enable a monthly scrub timer for every imported pool."""
    if not _has_cmd("zpool"):
        return "skipped (ZFS unavailable)"
    pools = _imported_pools()
    if not pools:
        return "skipped (no pools imported)"
    if not dry:
        for pool in pools:
            subprocess.run(
                ["systemctl", "enable", "--now", f"zfs-scrub-monthly@{pool}.timer"],
                check=False,
                capture_output=True,
            )
    return "monthly: " + ", ".join(pools)


def _step_esp_mirror(dry: bool, warnings: list[str]) -> str:
    """Mirror the ESP to every other pool disk so any disk can boot alone.

    Only meaningful on a mirrored pool; skips cleanly on single-disk setups.
    """
    if not _has_cmd("zpool"):
        return "skipped (ZFS unavailable)"
    status = subprocess.run(["zpool", "status"], capture_output=True, text=True).stdout
    if "mirror" not in status:
        return "skipped (no mirror vdev)"
    if not _is_mount("/boot/efi"):
        warnings.append(
            "EFI mirror: /boot/efi is not mounted; cannot mirror the bootloader. "
            "Mount the ESP and re-run setup."
        )
        return "skipped (/boot/efi not mounted)"

    script = _ESP_SYNC_SCRIPT_BODY.format(esp_guid=_ESP_TYPE_GUID)
    _log.info("Installing EFI mirror timer (%s).", _ESP_SYNC_TIMER)
    if not dry:
        _write_executable(_ESP_SYNC_SCRIPT, script)
        _ESP_SYNC_SERVICE.write_text(
            _ESP_SYNC_SERVICE_BODY.format(script=_ESP_SYNC_SCRIPT)
        )
        _ESP_SYNC_TIMER.write_text(_ESP_SYNC_TIMER_BODY)
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        subprocess.run(
            ["systemctl", "enable", "--now", _ESP_SYNC_TIMER.name],
            check=False,
            capture_output=True,
        )
        # Do one sync now so the secondary disk is bootable immediately.
        subprocess.run([str(_ESP_SYNC_SCRIPT)], check=False, capture_output=True)
    return "daily; synced now"


def _step_auto_update(args: argparse.Namespace, dry: bool, warnings: list[str]) -> str:
    """Install a timer that pulls origin/<branch> from GitHub and redeploys."""
    if getattr(args, "no_auto_update", False):
        return "disabled (--no-auto-update)"

    repo_dir = Path(
        getattr(args, "repo_dir", None)
        or detect_repo_dir(Path(__file__))
        or DEFAULT_REPO_DIR
    )
    branch = getattr(args, "branch", None) or DEFAULT_BRANCH
    minutes = int(getattr(args, "update_interval", None) or DEFAULT_UPDATE_MINUTES)

    summary, warns = install_github_autoupdate(
        repo_dir=repo_dir,
        branch=branch,
        minutes=minutes,
        restart_service="malmberg-server",
        run_as_user=_SYSTEM_USER,
        dry=dry,
    )
    warnings.extend(warns)
    return summary


def _step_pin(dry: bool) -> str:
    """Generate (or load existing) pairing PIN."""
    if _PIN_FILE.is_file():
        existing = _PIN_FILE.read_text().strip()
        if existing.isdigit() and len(existing) == 6:
            _log.info("Pairing PIN already set.")
            return existing
    pin = f"{random.randint(0, 999999):06d}"
    if not dry:
        _PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PIN_FILE.write_text(pin + "\n")
        _PIN_FILE.chmod(0o640)
    return pin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_root() -> None:
    if os.getuid() != 0:
        _log.error(
            "The setup command must be run as root: "
            "sudo uv run python -m malmberg_server setup"
        )
        sys.exit(2)


def _zfs_dataset_exists(dataset: str) -> bool:
    """Return True if the named ZFS dataset is present."""
    return (
        subprocess.run(
            ["zfs", "list", "-H", "-o", "name", dataset],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def _imported_pools() -> list[str]:
    """Return the names of all currently imported ZFS pools."""
    result = subprocess.run(
        ["zpool", "list", "-H", "-o", "name"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.split() if line]


def _mem_total_bytes() -> int | None:
    """Return total system RAM in bytes, or None if it cannot be read."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _is_mount(path: str) -> bool:
    """Return True if *path* is a mount point (robust under chroot/bind)."""
    return os.path.ismount(path)


def _print_summary(
    steps: list[tuple[str, str]],
    warnings: list[str],
    pin: str,
) -> None:
    width = 60
    print()
    print("=" * width)
    print("  Malmberg Server -- Provisioning Complete")
    print("=" * width)
    for label, detail in steps:
        print(f"  {label:<24} {detail}")
    if warnings:
        print()
        print("  Warnings:")
        for w in warnings:
            print(f"    ! {w}")
    print()
    print(f"  PAIRING PIN:  {pin}")
    print()
    print("  Show this PIN to anyone setting up a Display.")
    print("  It changes on each new provisioning run.")
    print()
    print("  Verify:  systemctl status malmberg-server")
    print("           curl http://localhost:8444/status")
    print("=" * width)
    print()
