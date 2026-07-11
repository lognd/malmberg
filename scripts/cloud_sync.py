"""Drive Malmberg cloud sync over the running server's HTTP API.

This talks to a running server (default http://127.0.0.1:8444) rather than
constructing a CloudSyncEngine in-process: the server already owns the media
store, the sync state file, and the background worker, so a second in-process
engine would risk two writers racing on cloud-state.json. HTTP keeps this
script a thin, safe remote control -- the same boundary the dashboard uses.

Subcommands:
  sync [--provider NAME]            trigger a sync (all providers, or one)
  show-status                       print per-provider diagnostics
  dry-run-deletable --provider NAME list items verified safe to delete
  delete --provider NAME --confirm  delete verified items (refuses w/o --confirm)
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def _base_url(args: argparse.Namespace) -> str:
    """Return the server base URL from --server (default local server port)."""
    return args.server.rstrip("/")


def _cmd_sync(args: argparse.Namespace) -> int:
    """POST /cloud/sync for all providers or a single named one."""
    body = {"provider": args.provider} if args.provider else {}
    resp = httpx.post(f"{_base_url(args)}/cloud/sync", json=body, timeout=30)
    print(json.dumps(resp.json(), indent=2))
    return 0 if resp.status_code == 200 else 1


def _cmd_status(args: argparse.Namespace) -> int:
    """GET /cloud/status and pretty-print the diagnostics."""
    resp = httpx.get(f"{_base_url(args)}/cloud/status", timeout=30)
    print(json.dumps(resp.json(), indent=2))
    return 0 if resp.status_code == 200 else 1


def _cmd_dry_run(args: argparse.Namespace) -> int:
    """GET /cloud/deletable for one provider (a dry run; deletes nothing)."""
    resp = httpx.get(
        f"{_base_url(args)}/cloud/deletable",
        params={"provider": args.provider},
        timeout=60,
    )
    print(json.dumps(resp.json(), indent=2))
    return 0 if resp.status_code == 200 else 1


def _cmd_delete(args: argparse.Namespace) -> int:
    """POST /cloud/delete for one provider; refuses unless --confirm is given."""
    if not args.confirm:
        print("Refusing to delete without --confirm.", file=sys.stderr)
        return 2
    body = {"provider": args.provider, "confirm": True}
    if args.cap is not None:
        body["cap"] = args.cap
    resp = httpx.post(f"{_base_url(args)}/cloud/delete", json=body, timeout=300)
    print(json.dumps(resp.json(), indent=2))
    return 0 if resp.status_code == 200 else 1


def main() -> int:
    """Parse args and dispatch the requested cloud-sync subcommand."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8444",
        help="Base URL of the running Malmberg server",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Trigger a sync")
    p_sync.add_argument("--provider", help="Limit to one provider by name")
    p_sync.set_defaults(func=_cmd_sync)

    p_status = sub.add_parser("show-status", help="Print per-provider status")
    p_status.set_defaults(func=_cmd_status)

    p_dry = sub.add_parser(
        "dry-run-deletable", help="List items verified safe to delete"
    )
    p_dry.add_argument("--provider", required=True, help="Provider name")
    p_dry.set_defaults(func=_cmd_dry_run)

    p_del = sub.add_parser("delete", help="Delete verified items from the cloud")
    p_del.add_argument("--provider", required=True, help="Provider name")
    p_del.add_argument("--confirm", action="store_true", help="Actually delete")
    p_del.add_argument("--cap", type=int, help="Max deletions this run")
    p_del.set_defaults(func=_cmd_delete)

    args = parser.parse_args()
    try:
        return int(args.func(args))
    except httpx.HTTPError as exc:
        print(f"Could not reach server: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
