"""Shared provisioning helpers used by both the server and display setup.

The GitHub auto-update timer is identical for both roles apart from which
systemd service it restarts and which user owns the checkout, so it lives here
in one place rather than being copied into each ``setup`` module.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from malmberg_core.logging import get_logger

_log = get_logger(__name__)

DEFAULT_BRANCH = "main"
DEFAULT_UPDATE_MINUTES = 10
DEFAULT_REPO_DIR = Path("/opt/malmberg")

_UPDATE_SCRIPT = Path("/usr/local/sbin/malmberg-update.sh")
_UPDATE_SERVICE = Path("/etc/systemd/system/malmberg-update.service")
_UPDATE_TIMER = Path("/etc/systemd/system/malmberg-update.timer")

_UPDATE_SCRIPT_TEMPLATE = """\
#!/bin/bash
# Managed by malmberg setup -- edits are overwritten on the next run.
# Pulls the latest code from GitHub and redeploys when origin/{branch} advances.
set -euo pipefail
export HOME=/root
REPO="{repo_dir}"
BRANCH="{branch}"
cd "$REPO"
git fetch --quiet origin "$BRANCH"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi
logger -t malmberg-update "new revision $REMOTE (was $LOCAL); updating"
git reset --hard "origin/$BRANCH"
UVLOG=/tmp/malmberg-update-uv.log
{uv} sync --frozen --project "$REPO" >"$UVLOG" 2>&1 || \
    logger -t malmberg-update "warning: uv sync failed (see $UVLOG)"
chown -R {user}:{user} "$REPO"
systemctl restart {service}
logger -t malmberg-update "updated to $REMOTE; {service} restarted"
"""

_UPDATE_SERVICE_TEMPLATE = """\
[Unit]
Description=Pull latest Malmberg from GitHub and redeploy
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={script}
"""

_UPDATE_TIMER_TEMPLATE = """\
[Unit]
Description=Check GitHub for Malmberg updates every {minutes} minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec={minutes}min
Persistent=true

[Install]
WantedBy=timers.target
"""


def has_cmd(cmd: str) -> bool:
    """Return True if *cmd* is resolvable on PATH."""
    return subprocess.run(["which", cmd], capture_output=True).returncode == 0


def write_exec(path: Path, content: str) -> None:
    """Write an executable script to *path* (mode 0755)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def detect_repo_dir(start: Path) -> Path | None:
    """Return the git checkout that contains *start*, if any."""
    for parent in start.resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def install_github_autoupdate(
    *,
    repo_dir: Path,
    branch: str,
    minutes: int,
    restart_service: str,
    run_as_user: str,
    dry: bool,
) -> tuple[str, list[str]]:
    """Install a systemd timer that pulls origin/<branch> and redeploys.

    Returns a ``(summary, warnings)`` tuple.  The updater fetches the deploy
    checkout, and on change hard-resets it, runs ``uv sync``, re-chowns the tree
    to *run_as_user*, and restarts *restart_service*.
    """
    warnings: list[str] = []

    if not (repo_dir / ".git").exists():
        warnings.append(
            f"Auto-update: '{repo_dir}' is not a git checkout, so unattended "
            "updates were not installed. Clone the repo there (or pass "
            "--repo-dir) and re-run setup."
        )
        return "skipped (no git checkout)", warnings

    uv = shutil.which("uv") or "/usr/local/bin/uv"
    if not Path(uv).exists() and not has_cmd("uv"):
        warnings.append(
            "Auto-update: 'uv' not found on PATH; the updater will pull code but "
            "cannot sync dependencies. Install uv system-wide (e.g. copy it to "
            "/usr/local/bin/uv)."
        )

    _log.info(
        "Installing auto-update timer: origin/%s every %d min from %s (restarts %s).",
        branch,
        minutes,
        repo_dir,
        restart_service,
    )
    if not dry:
        # Root must trust the (possibly non-root-owned) checkout.
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", str(repo_dir)],
            check=False,
        )
        write_exec(
            _UPDATE_SCRIPT,
            _UPDATE_SCRIPT_TEMPLATE.format(
                repo_dir=repo_dir,
                branch=branch,
                uv=uv,
                user=run_as_user,
                service=restart_service,
            ),
        )
        _UPDATE_SERVICE.write_text(
            _UPDATE_SERVICE_TEMPLATE.format(script=_UPDATE_SCRIPT)
        )
        _UPDATE_TIMER.write_text(_UPDATE_TIMER_TEMPLATE.format(minutes=minutes))
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        subprocess.run(
            ["systemctl", "enable", "--now", _UPDATE_TIMER.name],
            check=False,
            capture_output=True,
        )
    return f"every {minutes}m from origin/{branch}", warnings
