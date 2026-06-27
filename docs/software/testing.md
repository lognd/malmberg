# Testing

## Automated tests

```bash
# All automated tests (unit + integration + system)
uv run pytest

# Unit tests only (fast, no file I/O except tmp_path)
uv run pytest tests/unit/

# Integration tests (real file I/O, ASGI server, UDP)
uv run pytest tests/integration/

# System tests (end-to-end: server + display + ServerProducer)
uv run pytest tests/system/

# Lint, format, and type check
make check
```

### Test layout

```
tests/
  unit/
    core/         -- malmberg_core: HAL, models, networking
    display/      -- slideshow producers, Slideshow state machine
    server/       -- ingest pipeline, MediaStore, backup, routes
  integration/
    -- server API full CRUD cycle via ASGI transport
    -- ingest pipeline with real file I/O
    -- display API with a controlled Slideshow
    -- UDP broadcast/listen round-trip on loopback
  system/
    -- server upload -> ServerProducer fetch -> cache written
    -- config merge pipeline end-to-end
  manual/         -- excluded from pytest; see below
```

`tests/unit/` tests never touch the network and use only `tmp_path` for file I/O.
`tests/integration/` uses real filesystem operations and ASGI transports but no
actual network sockets (except UDP). `tests/system/` runs both the server and
display FastAPI apps via `httpx` ASGI transport and verifies the full data flow.

`asyncio_mode = "auto"` is set in `pyproject.toml`, so async test functions do not
need `@pytest.mark.asyncio`.

### Coverage

```bash
uv run pytest --cov=src --cov-report=html
open htmlcov/index.html   # macOS
xdg-open htmlcov/index.html   # Linux
```

---

## Manual hardware tests

The automated suite cannot test pygame rendering, mpv playback, GPIO pins, or the
full server-display pairing flow on real hardware. The manual runner covers all of
that.

Run it on the target device (Pi or server machine):

```bash
# See all available tests and their dependencies
uv run python tests/manual/runner.py --list

# Run everything interactively (opens windows, asks for confirmation)
uv run python tests/manual/runner.py --all

# Run a single test group
uv run python tests/manual/runner.py --test t05_picture_display

# Non-interactive mode (skips tests that need human confirmation)
uv run python tests/manual/runner.py --all --no-interactive
```

### Test groups

Tests run in dependency order. If a dependency fails, all dependent tests are
automatically skipped (marked `DEP_FAIL`).

| Group | Name | What it tests |
|-------|------|---------------|
| `t01_prereqs` | Prerequisites | Python packages, system tools |
| `t02_config_load` | Config loading | `ServerConfig` and `DisplayConfig` merge pipeline |
| `t03_hal_detection` | HAL detection | `get_hardware_profile()`, `hardware.toml` read/write |
| `t04_pygame_display` | pygame window | Opens an 800x480 pygame window; user confirms it appeared |
| `t05_picture_display` | Picture display | `PictureDisplay` with a generated test PNG |
| `t06_video_display` | Video display | `VideoDisplay` with mpv (skipped if mpv not installed) |
| `t07_web_display` | Web display | `WebDisplay` with playwright (skipped if not installed) |
| `t08_udp_broadcast` | UDP broadcast | Round-trip broadcast/listen on loopback |
| `t09_server_live` | Server (live) | Real uvicorn; upload a file, list it, fetch it |
| `t10_e2e_full` | Full E2E | Server + display running, upload, display fetches and renders |

### Logs

Each test run writes logs to `tests/manual/logs/<timestamp>/`. Each group gets its
own log file. The runner prints a summary at the end listing any WARNING or ERROR
lines from each test, making it easy to diagnose failures without reading full logs.

Logs are excluded from git (`.gitignore`) and from `make clean`.

---

## Running in CI

The automated suite (`tests/unit/`, `tests/integration/`, `tests/system/`) is
designed to run in any CI environment without display hardware. Optional deps
(pygame, mpv, playwright) are never imported by the automated tests.

The UDP integration test (`test_networking_integration.py`) is marked
`skipif(sys.platform == "win32")` because UDP broadcast on loopback is unreliable
on Windows.
