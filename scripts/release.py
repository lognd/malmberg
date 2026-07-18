#!/usr/bin/env python3
"""Bump patch version, build, and publish to PyPI."""

import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def bump_patch(version: str) -> str:
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def main() -> None:
    load_dotenv(Path(__file__).parent.parent / ".env")

    text = PYPROJECT.read_text()

    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        print("error: could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)

    old = m.group(1)
    new = bump_patch(old)
    updated = text[: m.start(1)] + new + text[m.end(1) :]
    PYPROJECT.write_text(updated)
    print(f"version: {old} -> {new}")

    subprocess.run(["uv", "build"], check=True)
    subprocess.run(["uv", "publish"], check=True)

    subprocess.run(["git", "add", "pyproject.toml"], check=True)
    subprocess.run(["git", "commit", "-m", f"release {new}"], check=True)
    subprocess.run(["git", "tag", f"v{new}"], check=True)
    print(f"tagged v{new} -- push with: git push && git push --tags")


if __name__ == "__main__":
    main()
