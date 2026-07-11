"""Interactive iCloud (pyicloud) session setup for Malmberg cloud sync.

Prompts for your Apple ID and an app-specific password, completes the 2FA
handshake, and caches the resulting session under fs_root/.cloud/icloud-session
(resolved from ServerConfig) so the server can reuse it without re-prompting.

IMPORTANT WARNING: pyicloud drives Apple's UNOFFICIAL private web API. It is
not sanctioned by Apple, can break without notice when Apple changes their
endpoints, and the cached session expires periodically (you will need to re-run
this script). Treat iCloud sync as best-effort. See docs/operations/cloud-sync.md.

Generate an app-specific password at https://appleid.apple.com (Sign-In and
Security -> App-Specific Passwords). Do NOT use your main Apple ID password.

This script does not crash when pyicloud is missing; it prints an install hint.
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path


def _session_dir(fs_root: Path) -> Path:
    """Return the cached-session dir from a ServerConfig on fs_root."""
    from malmberg_server.app.config import ServerConfig

    return ServerConfig(fs_root=fs_root).cloud_icloud_session_path()


def main() -> int:
    """Parse args, run the pyicloud login + 2FA flow, and cache the session."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fs-root",
        type=Path,
        default=Path("/fs"),
        help="Media filesystem root (default: /fs)",
    )
    parser.add_argument("--username", help="Apple ID (prompted if omitted)")
    args = parser.parse_args()

    try:
        import pyicloud
    except ImportError:
        print(
            "pyicloud is not installed.\n"
            "Install the extra:  uv sync --extra cloud-icloud"
        )
        return 1

    username = args.username or input("Apple ID: ").strip()
    password = getpass.getpass("App-specific password: ")

    session_dir = _session_dir(args.fs_root)
    session_dir.mkdir(parents=True, exist_ok=True)

    api = pyicloud.PyiCloudService(
        username, password, cookie_directory=str(session_dir)
    )

    if api.requires_2fa:
        code = input("Two-factor code from your Apple device: ").strip()
        if not api.validate_2fa_code(code):
            print("Failed to verify the two-factor code.")
            return 1
        if not api.is_trusted_session:
            api.trust_session()
    elif api.requires_2sa:
        devices = api.trusted_devices
        for i, device in enumerate(devices):
            print(f"  {i}: {device.get('deviceName', device)}")
        idx = int(input("Device index to receive a code: ").strip())
        device = devices[idx]
        if not api.send_verification_code(device):
            print("Failed to send the verification code.")
            return 1
        code = input("Verification code: ").strip()
        if not api.validate_verification_code(device, code):
            print("Failed to verify the code.")
            return 1

    print(f"iCloud session cached under {session_dir}")
    print(
        "Set MALMBERG_CLOUD_ICLOUD_ENABLED=1, "
        f"MALMBERG_CLOUD_ICLOUD_USERNAME={username}, and export the "
        "app-specific password as MALMBERG_CLOUD_ICLOUD_PASSWORD on the server."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
