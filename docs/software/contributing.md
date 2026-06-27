# Contributing

## Setup

```bash
git clone https://github.com/lognd/malmberg
cd malmberg
uv sync --dev
```

The `--dev` flag installs test and lint tools (`pytest`, `ruff`, `ty`, `httpx`,
`frob`, etc.) declared in `[dependency-groups.dev]` of `pyproject.toml`. Optional
display and cloud extras are not installed by default.

## Daily workflow

```bash
make check      # ruff --fix + ruff format + ty type check
uv run pytest   # all automated tests
```

Before committing, both must pass cleanly. `make check` applies safe auto-fixes in
place; commit the changes it makes alongside your own.

## Exploring the codebase

The project uses `frob` for cheap codebase navigation:

```bash
uv run python -m frob map src/           # project structure with token counts
uv run python -m frob outline src/file.py  # class/function signatures only
uv run python -m frob xref symbol src/    # find all callers/definitions
```

## Coding conventions

These are the non-obvious rules. The full reference is in
[design/reference.md](../design/reference.md#12-coding-standards).

- `from __future__ import annotations` in every module, always first.
- All public functions and methods are fully type-annotated. `ty check src/` is the
  type checker. Optional deps that are not installed produce `unresolved-import`
  errors which are suppressed with `--ignore unresolved-import`; do not add `# type:
  ignore` comments to silence them per-line.
- `malmberg_core.logging.get_logger(__name__)` is the only way to log. No
  `print()` in library or application code.
- `typani.Result` for any fallible operation a caller must handle. `danger_ok` and
  `danger_err` are **properties**, not methods -- never append `()`. Use exceptions
  only for genuinely unrecoverable states.
- Pydantic v2 throughout. Use `model_config = {}` not `class Config`. Use
  `model_copy(update=...)`, `model_dump()`, `model_dump_json()`,
  `model_validate_json()`.
- Optional hardware deps (`pygame`, `mpv`, `playwright`) are top-level imports in
  their own module files (e.g. `display/picture.py`, `display/video.py`). They
  fail fast at module import time if the package is missing. The exception is
  `producers/directory.py`, which defers `PictureDisplay`/`VideoDisplay` imports
  inside the generator body to avoid pulling transitive deps into test environments.
- Never branch on `sys.platform` or inspect `/proc/cpuinfo`. Always branch on
  `HardwareProfile` capability fields.
- `asyncio` only. No `threading` or `multiprocessing` in application code except
  where a third-party library (e.g. uvicorn signal handling in tests) forces it.
  Blocking I/O goes through `loop.run_in_executor`.

## Commit style

- Subject line: present-tense imperative, <= 72 characters.
  Good: `Add SHA-256 deduplication to handle_upload`
  Bad: `Added deduplication`, `WIP`, `fix stuff`
- Body: explains **why**, not what. The diff already shows what changed.
- Group related changes into one commit. Do not mix unrelated concerns.
- Do not include "Co-authored-by" or AI attribution lines.
- Do not amend published commits; create a new one instead.

## Adding a new cloud provider

1. Implement `CloudProvider(ABC)` in
   `src/malmberg_server/ingest/cloud/<name>.py`. The protocol requires `name: str`,
   `account: str`, `async def poll(self) -> AsyncIterator[MediaItem]`, and
   `async def download(self, item, dest)`.
2. Add the provider to the `[[cloud.provider]]` TOML schema in
   `ServerConfig.from_external`.
3. Add a pip extra in `pyproject.toml` (e.g. `[cloud-myprovider]`) with the
   provider's dependencies.
4. Write unit tests in `tests/unit/server/test_cloud_<name>.py`. Mock all network
   calls; do not make real API requests in tests.

## Adding a new display backend

1. Implement `Displayable` in `src/malmberg_display/display/<name>.py`. The ABC
   requires `async load(self, ctx: LoadContext)` and
   `async display(self, ctx: DisplayContext)`.
2. Import the new module and its deps at the top of the file (not lazily) so that
   missing deps fail at module import time rather than at runtime.
3. Update `CachedItem.load()` in
   `src/malmberg_display/slideshow/producers/server.py` if the new backend should
   be selected automatically by file extension (add the extension to
   `_VIDEO_SUFFIXES` or add a new branch).
4. Write tests in `tests/unit/display/`. If the backend requires hardware, cover
   the logic in unit tests by mocking the hardware library, and add a manual test
   in `tests/manual/tests/`.

## Running optional extras locally

```bash
# Display extras (pygame, Pillow, python-mpv)
uv sync --extra display

# Web overlay support (playwright + Chromium)
uv sync --extra web-overlays
playwright install chromium

# All extras
uv sync --extra all
```
