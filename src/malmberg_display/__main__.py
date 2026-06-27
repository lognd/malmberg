"""Entrypoint: python -m malmberg_display [options]"""

from __future__ import annotations

import argparse
from pathlib import Path

from malmberg_core.compat import toml
from malmberg_display.app import DisplayApp, DisplayConfig

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Malmberg display role")
    parser.add_argument("--config", metavar="PATH", help="Path to display.toml")
    parser.add_argument("--host", metavar="HOST", help="Bind host")
    parser.add_argument("--port", metavar="PORT", type=int, help="Bind port")
    parser.add_argument("--media-dir", metavar="DIR", help="Local media directory")
    args = parser.parse_args()

    cfg_path = (
        Path(args.config)
        if args.config
        else Path("~/.config/malmberg/display.toml").expanduser()
    )
    toml_cfg: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, "rb") as f:
            toml_cfg = toml.load(f)

    app = DisplayApp(DisplayConfig.from_external(args, toml_cfg))
    app()
