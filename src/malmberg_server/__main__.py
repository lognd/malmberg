"""Entrypoint: python -m malmberg_server [setup|run] [options]"""

from __future__ import annotations

import argparse
from pathlib import Path

from malmberg_core.compat import toml

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Malmberg server role",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Sub-commands:\n"
            "  setup   Provision this machine (run as root)\n"
            "  run     Start the server (default if no sub-command given)\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- setup sub-command ---------------------------------------------------
    setup_p = subparsers.add_parser(
        "setup",
        help="Provision this machine as a Malmberg server (requires root)",
    )
    setup_p.add_argument(
        "--fs-root",
        metavar="DIR",
        default="/fs",
        help="Media filesystem root (default: /fs)",
    )
    setup_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )
    setup_p.add_argument(
        "--no-enable",
        action="store_true",
        help="Write the systemd unit but do not enable or start the service",
    )

    # -- run sub-command (and top-level flags) --------------------------------
    run_p = subparsers.add_parser(
        "run",
        help="Start the server (default)",
    )
    for p in (parser, run_p):
        p.add_argument("--config", metavar="PATH", help="Path to server.toml")
        p.add_argument("--host", metavar="HOST", help="Bind host")
        p.add_argument("--port", metavar="PORT", type=int, help="Bind port")
        p.add_argument("--fs-root", metavar="DIR", help="Media filesystem root")

    args = parser.parse_args()

    if args.command == "setup":
        from malmberg_server.setup import run as setup_run

        setup_run(args)
    else:
        # Default: run the server (handles both explicit "run" and no sub-command).
        from malmberg_server.app import ServerApp, ServerConfig

        cfg_path = (
            Path(args.config)
            if getattr(args, "config", None)
            else Path("~/.config/malmberg/server.toml").expanduser()
        )
        toml_cfg: dict = {}
        if cfg_path.is_file():
            with open(cfg_path, "rb") as f:
                toml_cfg = toml.load(f)

        app = ServerApp(ServerConfig.from_external(args, toml_cfg))
        app()
