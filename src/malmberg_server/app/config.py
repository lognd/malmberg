"""ServerConfig: merged configuration for the server role."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator

from malmberg_core.compat import Self

HidePolicy = Literal["delete", "keep"]


class ServerConfig(BaseModel):
    """Runtime configuration for the server role."""

    host: str = "0.0.0.0"
    port: int = 8444
    config_path: Path = Path("~/.config/malmberg/server.toml")
    fs_root: Path = Path("/fs")
    """Root of the media filesystem (see architecture.md Section 3.4)."""
    hide_policy: HidePolicy = "delete"
    trash_purge_days: int = 30
    max_upload_mb: int = 500
    backup_retention: int = 20
    """Number of ZFS snapshots to retain (exponential-backoff policy)."""
    log_retention: int = 10
    """Number of log files to retain (same policy as backup_retention)."""
    display_url: Optional[str] = None
    """Base URL of a single paired display's control API (e.g. http://10.0.0.5:8443).

    When None (and no `displays` map is set), /control/* returns 503.
    """
    displays: dict[str, str] = {}
    """Named displays (name -> control base URL) for multi-display control.

    Set via env MALMBERG_DISPLAY_URLS as "name=url,name=url". Takes precedence
    over `display_url`; a lone `display_url` is treated as one display named
    'display'.
    """

    cloud_icloud_enabled: bool = False
    """Enable the iCloud cloud-sync provider (see malmberg_server.cloud)."""
    cloud_icloud_username: Optional[str] = None
    """Apple ID for iCloud sync; the password is read from an env var, never here."""
    cloud_icloud_session_dir: Optional[Path] = None
    """Cached pyicloud session dir; None -> fs_root/.cloud/icloud-session/."""
    cloud_google_photos_enabled: bool = False
    """Enable the Google Photos cloud-sync provider (app-uploaded items only)."""
    cloud_google_client_secrets: Optional[Path] = None
    """OAuth client-secret file; None -> fs_root/.cloud/google-client-secret.json."""
    cloud_google_token: Optional[Path] = None
    """OAuth token file; None -> fs_root/.cloud/google-photos-token.json."""
    cloud_sync_interval_s: int = 3600
    """Seconds between background auto-sync sweeps."""
    cloud_delete_cap: int = 200
    """Hard ceiling on cloud deletions per delete_verified run."""

    @field_validator("max_upload_mb")
    @classmethod
    def _upload_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_upload_mb must be >= 1")
        return v

    @field_validator("cloud_sync_interval_s")
    @classmethod
    def _interval_min(cls, v: int) -> int:
        if v < 60:
            raise ValueError("cloud_sync_interval_s must be >= 60")
        return v

    @field_validator("cloud_delete_cap")
    @classmethod
    def _cap_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("cloud_delete_cap must be >= 1")
        return v

    def cloud_icloud_session_path(self) -> Path:
        """Resolve the iCloud session dir, defaulting under fs_root/.cloud/."""
        return self.cloud_icloud_session_dir or (
            self.fs_root / ".cloud" / "icloud-session"
        )

    def cloud_google_client_secrets_path(self) -> Path:
        """Resolve the Google client-secret path, defaulting under fs_root/.cloud/."""
        return self.cloud_google_client_secrets or (
            self.fs_root / ".cloud" / "google-client-secret.json"
        )

    def cloud_google_token_path(self) -> Path:
        """Resolve the Google token path, defaulting under fs_root/.cloud/."""
        return self.cloud_google_token or (
            self.fs_root / ".cloud" / "google-photos-token.json"
        )

    @staticmethod
    def _env_bool(v: str) -> bool:
        """Parse a boolean env var ('1'/'true'/'yes', case-insensitive)."""
        return v.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _args_to_dict(args: argparse.Namespace) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if args.host:
            result["host"] = args.host
        if args.port:
            result["port"] = args.port
        if args.config:
            result["config_path"] = Path(args.config)
        if getattr(args, "fs_root", None):
            result["fs_root"] = Path(args.fs_root)
        return result

    @staticmethod
    def _env_overrides() -> dict[str, Any]:
        result: dict[str, Any] = {}
        if v := os.environ.get("MALMBERG_HOST"):
            result["host"] = v
        if v := os.environ.get("MALMBERG_PORT"):
            result["port"] = int(v)
        if v := os.environ.get("MALMBERG_FS_ROOT"):
            result["fs_root"] = Path(v)
        if v := os.environ.get("MALMBERG_HIDE_POLICY"):
            result["hide_policy"] = v
        if v := os.environ.get("MALMBERG_DISPLAY_URL"):
            result["display_url"] = v
        if v := os.environ.get("MALMBERG_DISPLAY_URLS"):
            displays: dict[str, str] = {}
            for pair in v.split(","):
                name, _, url = pair.partition("=")
                if name.strip() and url.strip():
                    displays[name.strip()] = url.strip()
            if displays:
                result["displays"] = displays
        if v := os.environ.get("MALMBERG_CLOUD_ICLOUD_ENABLED"):
            result["cloud_icloud_enabled"] = ServerConfig._env_bool(v)
        if v := os.environ.get("MALMBERG_CLOUD_ICLOUD_USERNAME"):
            result["cloud_icloud_username"] = v
        if v := os.environ.get("MALMBERG_CLOUD_ICLOUD_SESSION_DIR"):
            result["cloud_icloud_session_dir"] = Path(v)
        if v := os.environ.get("MALMBERG_CLOUD_GOOGLE_PHOTOS_ENABLED"):
            result["cloud_google_photos_enabled"] = ServerConfig._env_bool(v)
        if v := os.environ.get("MALMBERG_CLOUD_GOOGLE_CLIENT_SECRETS"):
            result["cloud_google_client_secrets"] = Path(v)
        if v := os.environ.get("MALMBERG_CLOUD_GOOGLE_TOKEN"):
            result["cloud_google_token"] = Path(v)
        if v := os.environ.get("MALMBERG_CLOUD_SYNC_INTERVAL_S"):
            result["cloud_sync_interval_s"] = int(v)
        if v := os.environ.get("MALMBERG_CLOUD_DELETE_CAP"):
            result["cloud_delete_cap"] = int(v)
        return result

    @classmethod
    def from_external(
        cls,
        args: argparse.Namespace,
        toml: dict[str, Any],
    ) -> Self:
        """Merge CLI args, env vars, and TOML into a validated ServerConfig."""
        merged: dict[str, Any] = {}
        merged.update(toml)
        merged.update(cls._env_overrides())
        merged.update(cls._args_to_dict(args))
        return cls(**merged)
