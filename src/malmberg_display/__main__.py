"""Entrypoint: python -m malmberg_display [setup|run] [options]"""

from __future__ import annotations

import argparse
from pathlib import Path

from malmberg_core.compat import toml

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Malmberg display role",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Sub-commands:\n"
            "  setup   Provision this machine (run as root)\n"
            "  run     Start the display (default if no sub-command given)\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- setup sub-command ---------------------------------------------------
    setup_p = subparsers.add_parser(
        "setup",
        help="Provision this machine as a Malmberg display (requires root)",
    )
    setup_p.add_argument(
        "--user",
        metavar="USER",
        help=(
            "Username that owns the X session and will run the display service "
            "(default: $SUDO_USER or 'pi')"
        ),
    )
    setup_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )
    setup_p.add_argument(
        "--no-enable",
        action="store_true",
        help="Write the systemd unit but do not enable the service",
    )
    setup_p.add_argument(
        "--no-auto-update",
        action="store_true",
        help="Do not install the GitHub auto-update timer",
    )
    setup_p.add_argument(
        "--repo-dir",
        metavar="DIR",
        help="Git checkout the auto-updater pulls into "
        "(default: this checkout, else /opt/malmberg)",
    )
    setup_p.add_argument(
        "--branch",
        metavar="NAME",
        default="main",
        help="Git branch the auto-updater tracks (default: main)",
    )
    setup_p.add_argument(
        "--update-interval",
        metavar="MIN",
        type=int,
        default=10,
        help="Minutes between GitHub update checks (default: 10)",
    )

    # -- run sub-command (and top-level flags) --------------------------------
    run_p = subparsers.add_parser(
        "run",
        help="Start the display (default)",
    )
    for p in (parser, run_p):
        p.add_argument("--config", metavar="PATH", help="Path to display.toml")
        p.add_argument("--host", metavar="HOST", help="Bind host")
        p.add_argument("--port", metavar="PORT", type=int, help="Bind port")
        p.add_argument("--media-dir", metavar="DIR", help="Local media directory")
        p.add_argument(
            "--server-url",
            metavar="URL",
            help="Explicit server base URL (skips UDP discovery)",
        )
        p.add_argument(
            "--width", metavar="PX", type=int, help="Display width in pixels"
        )
        p.add_argument(
            "--height", metavar="PX", type=int, help="Display height in pixels"
        )

    args = parser.parse_args()

    if args.command == "setup":
        from malmberg_display.setup import run as setup_run

        setup_run(args)
    else:
        # Default: run the display (handles both explicit "run" and no sub-command).
        from malmberg_display.app import DisplayApp, DisplayConfig

        cfg_path = (
            Path(args.config)
            if getattr(args, "config", None)
            else Path("~/.config/malmberg/display.toml").expanduser()
        )
        toml_cfg: dict = {}
        if cfg_path.is_file():
            with open(cfg_path, "rb") as f:
                toml_cfg = toml.load(f)

        app = DisplayApp(DisplayConfig.from_external(args, toml_cfg))
        app()
