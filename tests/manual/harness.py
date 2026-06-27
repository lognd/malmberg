"""Shared types for manual test modules: TestContext and TestSkip."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


class TestSkip(Exception):
    """Raise from a test to mark it skipped (prerequisite hardware absent)."""


class TestContext:
    """Passed into every test's run() function."""

    def __init__(self, log_dir: Path, no_interactive: bool) -> None:
        self.log_dir = log_dir
        self.no_interactive = no_interactive
        self._log: Optional[logging.Logger] = None

    def setup_logger(self, name: str) -> logging.Logger:
        log_path = self.log_dir / f"{name}.log"
        logger = logging.getLogger(f"manual.{name}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("  %(levelname)-8s %(message)s"))
        logger.addHandler(fh)
        logger.addHandler(ch)
        self._log = logger
        return logger

    def prompt(self, question: str, default: str = "y") -> str:
        """Ask the user a yes/no question; returns 'y' or 'n'."""
        if self.no_interactive:
            return default
        hint = "[Y/n]" if default == "y" else "[y/N]"
        ans = input(f"  >> {question} {hint}: ").strip().lower()
        return ans if ans in ("y", "n") else default

    def confirm(self, message: str) -> None:
        """Prompt the user to press Enter after observing something."""
        if self.no_interactive:
            return
        input(f"  >> {message}  (press Enter to continue)")
