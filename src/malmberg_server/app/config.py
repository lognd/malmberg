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
    """Base URL of the paired display's control API (e.g. http://10.0.0.5:8443).

    When None, the /control/* endpoints return 503 rather than forwarding.
    """

    @field_validator("max_upload_mb")
    @classmethod
    def _upload_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_upload_mb must be >= 1")
        return v

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
