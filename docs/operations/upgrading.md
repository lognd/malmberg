# Upgrading

## Upgrading the software

Pull the latest changes and re-sync dependencies:

```bash
cd malmberg
git pull
uv sync --dev
```

If you are running the display extras:

```bash
uv sync --dev --extra display
```

Restart both services after upgrading:

```bash
sudo systemctl restart malmberg-server
sudo systemctl restart malmberg-display
```

Both services will be briefly unavailable during the restart. The display falls back
to its offline cache automatically.

---

## Checking the current version

From the command line:

```bash
uv run python -c "from malmberg_core import __version__; print(__version__)"
```

From the API (no restart required):

```bash
curl -s http://localhost:8444/ | python3 -m json.tool
curl -s http://localhost:8443/ | python3 -m json.tool
```

Both return a `Tag` object whose `version` field is the package version.

---

## Upgrading Python

The project requires Python >= 3.10. To upgrade the interpreter:

```bash
# Ubuntu
sudo apt install python3.12 python3.12-venv

# Tell uv to use the new interpreter
uv python pin 3.12
uv sync
```

Verify after syncing:

```bash
uv run python --version
uv run pytest   # confirm tests still pass
```

---

## Data migration

The media index (`/fs/logs/media-index.jsonl`) stores one `MediaItem` JSON object
per line. The format is forward-compatible: fields added in a newer version are
silently ignored by older versions; removed fields become null.

No migration step is required between patch versions.

If a future minor or major version adds required fields to `MediaItem`, the changelog
will document a migration command. Migrations will always be runnable with:

```bash
uv run python -m malmberg_server migrate
```

This command does not yet exist; it is reserved for future use.

---

## Rollback

To roll back to a previous version:

```bash
cd malmberg
git checkout <tag-or-commit>
uv sync
sudo systemctl restart malmberg-server malmberg-display
```

The media index format is stable across versions. Rollback does not require a data
migration in either direction.

If you modified `hardware.toml` after the upgrade and need to restore the previous
version, it is a plain TOML file under `~/.config/malmberg/hardware.toml` -- restore
it from your backup or regenerate it by re-running `setup`.

---

## Upgrading ZFS

ZFS pool and dataset upgrades are independent of the Malmberg software upgrade. When
upgrading ZFS itself (`zfsutils-linux`), verify that the `malmberg` user's `zfs allow`
permissions are preserved:

```bash
zfs allow tank/malmberg
# should include: snapshot, destroy, send for user malmberg
```

If the permissions were lost (this can happen on some ZFS package upgrades), restore
them:

```bash
sudo zfs allow malmberg snapshot,destroy,send tank/malmberg
```
