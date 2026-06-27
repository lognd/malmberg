# Technology Reference, Coding Standards, and Module Ownership

## 11. Technology Reference

| Concern | Library / Tool | Notes |
|---------|---------------|-------|
| API framework | `fastapi` + `uvicorn` | Both roles |
| Web dashboard | `htmx` + `jinja2` | Served by FastAPI; no JS build step |
| Data validation | `pydantic` v2 | All external data |
| Error handling | `typani` | Internal Result/Unreachable types |
| Image decode | `Pillow` | EXIF, resize, format convert |
| Image display | `pygame` (SDL2) | Full-screen, transitions |
| Video playback | `mpv` via `python-mpv` | HW decode gated by HAL profile |
| Web overlay | `playwright-python` + Chromium | Extra `[web-overlays]`; HAL-gated |
| Cloud: iCloud | `pyicloud` | Extra `[cloud-icloud]` |
| Cloud: Google Photos | `google-auth` + device flow | Extra `[cloud-googlephotos]` |
| Privacy filter | `insightface` or `ultralytics` | Extra `[privacy]`; never auto-installed |
| Geocoding | `geopy` + local Nominatim cache | EXIF location display |
| Encryption | `cryptography` (Fernet) | Token storage at rest |
| Keyring | `keyring` | OS-level secret storage |
| ZFS | subprocess (`zfs`, `zpool`) | Snapshot, send/recv; no Python bindings needed |
| Provisioning | Python stdlib + `subprocess` | No Ansible/Chef dependency |
| Status panel | `luma.oled` / `luma.eink` | HAL-gated; no-op if bus == "none" |

## 12. Coding Standards

- **Imports:** `from __future__ import annotations` in every module. stdlib,
  then third-party, then local. Grouped by blank line.
- **Python version:** >= 3.10. Use `malmberg_core.compat` for 3.11+ stdlib
  additions (`tomllib`, `Self`).
- **Types:** all public functions and methods are fully annotated. `ty` is the
  type checker (`ty check src/`). No `Any` except at true external boundaries.
- **Errors:** use `typani.Result` for fallible operations that callers must
  handle. Use exceptions only for truly unrecoverable states. Never swallow
  exceptions silently.
- **Async:** `asyncio` only. No `threading` or `multiprocessing` except where a
  third-party library forces it (wrap in `loop.run_in_executor`).
- **Optional imports:** extras that may not be installed are imported inside
  the function or class that uses them, guarded by a `try/except ImportError`
  that raises a clear `RuntimeError` with install instructions. Never at module
  level.
- **HAL gating:** never branch on platform strings or `sys.platform` in
  application code. Always branch on `profile.<capability>`.
- **Tests:** `pytest`. Unit tests mock no I/O except filesystem (use
  `tmp_path`). Integration tests are marked `@pytest.mark.integration` and
  require explicit opt-in. Target >= 80% branch coverage on `malmberg_core`.
- **Linter:** `ruff` with `E, F, W, I` rules. Line length 88. CI blocks on any
  ruff error.
- **Comments:** only for non-obvious WHY. No docstring walls. No TODO comments
  in committed code.
- **No print statements** in library or application code; use `get_logger`.

## 13. Module Ownership

| Module | Owner | Description |
|--------|-------|-------------|
| `malmberg_core` | Logan Dapp | Shared primitives; changes here affect both roles |
| `malmberg_core.hal` | Logan Dapp | Hardware Abstraction Layer and profiles |
| `malmberg_server.app` | Logan Dapp | App lifecycle, config, entrypoint |
| `malmberg_server.api` | Logan Dapp | FastAPI routes and HTMX dashboard |
| `malmberg_server.ingest` | Logan Dapp | USB, cloud, upload pipelines |
| `malmberg_server.ingest.cloud` | Logan Dapp | Per-provider cloud plugins |
| `malmberg_server.backup` | Logan Dapp | ZFS snapshot, master/slave sync |
| `malmberg_server.ui` | Logan Dapp | Server status panel driver |
| `malmberg_server.setup` | Logan Dapp | Ubuntu provisioning script |
| `malmberg_display.app` | Logan Dapp | App lifecycle, config, entrypoint |
| `malmberg_display.api` | Logan Dapp | FastAPI routes (handshake + remote control) |
| `malmberg_display.display` | Logan Dapp | `Displayable` protocol, rendering backends |
| `malmberg_display.slideshow` | Logan Dapp | Slideshow orchestrator, producers |
| `malmberg_display.ui` | Logan Dapp | Button input, overlays, Display status panel |
| `malmberg_display.setup` | Logan Dapp | Pi provisioning script |
