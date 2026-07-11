from __future__ import annotations

import logging
import logging.config
from pathlib import Path

from malmberg_core.compat import toml

_CONFIG_PATH = Path(__file__).parent / "config.toml"
_initialized = False


def _init() -> None:
    global _initialized
    if _initialized:
        return
    with _CONFIG_PATH.open("rb") as f:
        cfg = toml.load(f)
    logging.config.dictConfig(cfg)
    # Silence very chatty third-party DEBUG logs (EXIF tag dumps, HTTP wire
    # traces) that would otherwise drown out our own diagnostics.
    for noisy in ("PIL", "httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _initialized = True


def get_logger(name: str) -> logging.Logger:
    _init()
    return logging.getLogger(name)
