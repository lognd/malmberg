"""DisplayConfig: merged configuration for the display role."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from malmberg_core.compat import Self


class DisplayConfig(BaseModel):
    """Runtime configuration for the display role.

    Fields are merged from (highest priority first):
    1. CLI flags
    2. Environment variables prefixed MALMBERG_
    3. TOML config file
    4. Defaults defined here
    """

    host: str = "0.0.0.0"
    port: int = 8443
    config_path: Path = Path("~/.config/malmberg/display.toml")
    cache_dir: Path = Path("~/.cache/malmberg/display")
    dwell_s: float = 10.0
    fade_duration_s: float = 0.5
    web_overlays: bool = False
    """Enable playwright-based web overlays (requires playwright_supported HAL flag)."""
    offline_cache_size: int = 500
    """Maximum number of items to keep in the offline LRU cache."""
    width: int = 1920
    height: int = 1080
    media_dir: Optional[Path] = None
    """If set, use a local directory as the media source instead of a server."""

    @field_validator("dwell_s")
    @classmethod
    def _dwell_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("dwell_s must be positive")
        return v

    @field_validator("offline_cache_size")
    @classmethod
    def _cache_size_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("offline_cache_size must be >= 1")
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
        if getattr(args, "media_dir", None):
            result["media_dir"] = Path(args.media_dir)
        return result

    @staticmethod
    def _env_overrides() -> dict[str, Any]:
        result: dict[str, Any] = {}
        if v := os.environ.get("MALMBERG_HOST"):
            result["host"] = v
        if v := os.environ.get("MALMBERG_PORT"):
            result["port"] = int(v)
        if v := os.environ.get("MALMBERG_DWELL_S"):
            result["dwell_s"] = float(v)
        if v := os.environ.get("MALMBERG_WEB_OVERLAYS"):
            result["web_overlays"] = v.lower() in ("1", "true", "yes")
        return result

    @classmethod
    def from_external(
        cls,
        args: argparse.Namespace,
        toml: dict[str, Any],
    ) -> Self:
        """Merge CLI args, env vars, and TOML into a validated DisplayConfig."""
        merged: dict[str, Any] = {}
        merged.update(toml)
        merged.update(cls._env_overrides())
        merged.update(cls._args_to_dict(args))
        return cls(**merged)
