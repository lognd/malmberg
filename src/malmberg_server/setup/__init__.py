"""Idempotent provisioning for the Malmberg server role.

Invoked as::

    sudo python -m malmberg_server setup [--fs-root /fs] [--dry-run] [--no-enable]

Every step is idempotent: it is safe to re-run after a partial install or
after an upgrade.  Steps that cannot be completed non-fatally (e.g. ZFS
unavailable) emit a warning and continue.

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
        if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
            problems.append(
                f"Required command '{cmd}' not found. "
                "Install it with: sudo apt install systemd passwd"
            )

    if subprocess.run(["which", "zfs"], capture_output=True).returncode != 0:
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

_FS_SUBDIRS = ("media", "uploads", "cloud", ".trash", "logs")

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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> None:
    """Run all provisioning steps.  Prints a summary on completion."""
    dry = getattr(args, "dry_run", False)
    no_enable = getattr(args, "no_enable", False)
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

    # 9. Cron jobs (trash purge + ZFS backup)
    _step_cron(fs_root, dry, warnings)
    steps.append(("Cron jobs", "trash purge + ZFS backup installed"))

    # 10. Pairing PIN
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
            f"Edit {_HARDWARE_TOML} manually if needed."
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
    """Create ZFS dataset if ZFS is available; otherwise warn."""
    if subprocess.run(["which", "zfs"], capture_output=True).returncode != 0:
        warnings.append(
            "ZFS not found.  Install with `sudo apt install zfsutils-linux` "
            "for snapshot-based backups.  Plain directory in use."
        )
        return "ZFS unavailable -- using plain directory"

    dataset = "tank/malmberg"
    check = subprocess.run(
        ["zfs", "list", "-H", "-o", "name", dataset],
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        _log.info("ZFS dataset '%s' already exists.", dataset)
        return f"{dataset} (already exists)"

    _log.info("Creating ZFS dataset '%s'.", dataset)
    if not dry:
        result = subprocess.run(
            ["zfs", "create", dataset],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            warnings.append(
                f"Could not create ZFS dataset '{dataset}': {result.stderr.strip()}. "
                "Create it manually: sudo zfs create tank/malmberg"
            )
            return f"{dataset} -- creation failed (see warnings)"

    # Grant malmberg user snapshot permissions.
    if not dry:
        subprocess.run(
            ["zfs", "allow", _SYSTEM_USER, "snapshot,destroy", dataset],
            check=False,
        )

    return f"{dataset} created"


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

    if subprocess.run(["which", "openssl"], capture_output=True).returncode != 0:
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
            f"snapshot('tank/malmberg')\"",
        ),
    ]

    if subprocess.run(["which", "crontab"], capture_output=True).returncode != 0:
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
