"""Interactive Google Photos OAuth setup for Malmberg cloud sync.

Walks you through the one-time Google Cloud Console steps, then runs the
installed-app OAuth flow and saves the resulting token where the server's
GooglePhotosProvider looks for it (fs_root/.cloud/google-photos-token.json by
default, resolved from ServerConfig).

IMPORTANT LIMITATION: since ~March 2025 the Google Photos Library API only
lets a third-party app see and download media THAT THE APP ITSELF UPLOADED,
and it exposes no delete operation at all. Connecting here will NOT give
Malmberg access to your full Google Photos library, and Malmberg can never
delete Google Photos items from the cloud. See docs/operations/cloud-sync.md.

This script does not crash when google-auth-oauthlib is missing; it prints an
install hint instead.
"""

from __future__ import annotations

import argparse
from pathlib import Path

_SCOPES = ["https://www.googleapis.com/auth/photoslibrary.appcreateddata"]

_STEPS = """
Google Cloud Console setup (one time):
  1. Create a project at https://console.cloud.google.com/
  2. Enable the "Photos Library API" for that project.
  3. Configure the OAuth consent screen (External, add yourself as a test user).
  4. Create an OAuth client ID of type "Desktop app".
  5. Download the client secret JSON (e.g. path/to/credentials.json).
"""


def _resolve_paths(fs_root: Path) -> tuple[Path, Path]:
    """Return (client_secrets_path, token_path) from a ServerConfig on fs_root."""
    from malmberg_server.app.config import ServerConfig

    cfg = ServerConfig(fs_root=fs_root)
    return cfg.cloud_google_client_secrets_path(), cfg.cloud_google_token_path()


def main() -> int:
    """Parse args, print setup steps, run the OAuth flow, and save the token."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fs-root",
        type=Path,
        default=Path("/fs"),
        help="Media filesystem root (default: /fs)",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        help="Path to the downloaded client secret JSON "
        "(default: fs_root/.cloud/google-client-secret.json)",
    )
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "google-auth-oauthlib is not installed.\n"
            "Install the extra:  uv sync --extra cloud-googlephotos"
        )
        return 1

    print(_STEPS)
    default_secrets, token_path = _resolve_paths(args.fs_root)
    secrets = args.credentials or default_secrets
    if not secrets.is_file():
        print(f"Client secret file not found: {secrets}")
        print("Download it from the Cloud Console and pass --credentials PATH.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), _SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Saved Google Photos token to {token_path}")
    print("Enable it with MALMBERG_CLOUD_GOOGLE_PHOTOS_ENABLED=1 on the server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
