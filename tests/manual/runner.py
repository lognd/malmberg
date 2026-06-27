#!/usr/bin/env python3
"""Manual hardware test runner for malmberg.

Usage:
    python tests/manual/runner.py --all
    python tests/manual/runner.py --list
    python tests/manual/runner.py --test t01_prereqs t02_pygame
    python tests/manual/runner.py --all --no-interactive

Tests run sequentially in dependency order.  Each test module exposes:
    TITLE: str
    DEPENDS: list[str]          (module name stems that must pass first)
    INTERACTIVE: bool           (requires a human to observe)

    def run(ctx: TestContext) -> None   (raises AssertionError or TestSkip on failure)

Log files are written to tests/manual/logs/<timestamp>/<test_name>.log.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
import textwrap
import traceback
from datetime import datetime
from pathlib import Path
from types import ModuleType

# harness must be importable before test modules are loaded
from harness import TestContext, TestSkip  # noqa: E402 (after sys.path setup)

MANUAL_DIR = Path(__file__).parent
TESTS_DIR = MANUAL_DIR / "tests"
LOGS_DIR = MANUAL_DIR / "logs"
SRC_DIR = MANUAL_DIR.parent.parent / "src"

# Ensure src/ and tests/manual/ are on path so malmberg packages and the
# harness module import cleanly from test modules.
for _p in (str(SRC_DIR), str(MANUAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------


def _load_module(stem: str) -> ModuleType:
    spec_path = TESTS_DIR / f"{stem}.py"
    if not spec_path.is_file():
        raise FileNotFoundError(f"No test module: {spec_path}")
    spec = importlib.util.spec_from_file_location(f"manual.tests.{stem}", spec_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _discover_all() -> list[str]:
    """Return test stems in filename order (t01_, t02_, ...)."""
    stems = sorted(
        p.stem for p in TESTS_DIR.glob("t[0-9]*.py") if p.name != "__init__.py"
    )
    return stems


# ---------------------------------------------------------------------------
# Runner logic
# ---------------------------------------------------------------------------

_PASS = "PASS"
_FAIL = "FAIL"
_SKIP = "SKIP"
_DEP_FAIL = "DEP_FAIL"


def _run_one(
    stem: str,
    ctx: TestContext,
    results: dict[str, str],
    mods: dict[str, ModuleType],
) -> str:
    mod = mods[stem]
    depends: list[str] = getattr(mod, "DEPENDS", [])
    interactive: bool = getattr(mod, "INTERACTIVE", False)

    for dep in depends:
        if results.get(dep) not in (_PASS, _SKIP):
            print(f"  [DEP_FAIL] skipping because dependency '{dep}' did not pass")
            return _DEP_FAIL

    if interactive and ctx.no_interactive:
        print("  [SKIP] interactive test skipped in --no-interactive mode")
        return _SKIP

    ctx.setup_logger(stem)
    try:
        mod.run(ctx)
        return _PASS
    except TestSkip as exc:
        print(f"  [SKIP] {exc}")
        return _SKIP
    except AssertionError as exc:
        print(f"  [FAIL] {exc}")
        traceback.print_exc()
        return _FAIL
    except Exception as exc:
        print(f"  [FAIL] unexpected error: {exc}")
        traceback.print_exc()
        return _FAIL


def run_tests(stems: list[str], no_interactive: bool) -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = LOGS_DIR / timestamp
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nLog directory: {log_dir}\n")

    ctx = TestContext(log_dir=log_dir, no_interactive=no_interactive)
    results: dict[str, str] = {}
    mods: dict[str, ModuleType] = {}

    for stem in stems:
        try:
            mods[stem] = _load_module(stem)
        except Exception as exc:
            print(f"[ERROR] could not load {stem}: {exc}")
            results[stem] = _FAIL

    for stem in stems:
        if stem not in mods:
            continue
        title = getattr(mods[stem], "TITLE", stem)
        print(f"\n{'=' * 60}")
        print(f"  {stem}: {title}")
        print(f"{'=' * 60}")
        outcome = _run_one(stem, ctx, results, mods)
        results[stem] = outcome

    # Summary table
    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    col = max(len(s) for s in stems) if stems else 10
    for stem in stems:
        outcome = results.get(stem, "?")
        title = getattr(mods.get(stem, object()), "TITLE", stem)  # type: ignore[arg-type]
        marker = {
            "PASS": "[PASS]",
            "FAIL": "[FAIL]",
            "SKIP": "[SKIP]",
            "DEP_FAIL": "[SKIP]",
        }.get(outcome, "[????]")
        print(f"  {marker}  {stem:<{col}}  {title}")

    counts = {
        k: sum(1 for v in results.values() if v == k)
        for k in (_PASS, _FAIL, _SKIP, _DEP_FAIL)
    }
    print(
        f"\n  Passed: {counts[_PASS]}  Failed: {counts[_FAIL]}  Skipped: {counts[_SKIP] + counts[_DEP_FAIL]}"
    )

    _print_log_digest(log_dir, stems)
    print(f"\nFull logs: {log_dir}\n")

    return 1 if counts[_FAIL] > 0 else 0


def _print_log_digest(log_dir: Path, stems: list[str]) -> None:
    """Print WARNING/ERROR lines from each log file under log_dir."""
    found_any = False
    for stem in stems:
        log_path = log_dir / f"{stem}.log"
        if not log_path.is_file():
            continue
        lines = [
            line.rstrip()
            for line in log_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            if " WARNING  " in line or " ERROR    " in line or " CRITICAL " in line
        ]
        if lines:
            if not found_any:
                print(f"\n{'=' * 60}")
                print("  LOG DIGEST (WARNING/ERROR lines)")
                print(f"{'=' * 60}")
                found_any = True
            print(f"\n  -- {stem} --")
            for line in lines:
                # Strip timestamp prefix for readability: keep level + message
                parts = line.split(" ", 2)
                short = line if len(parts) < 3 else parts[-1]
                print(f"    {short}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    all_stems = _discover_all()

    parser = argparse.ArgumentParser(
        description="Malmberg manual hardware test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python tests/manual/runner.py --list
              python tests/manual/runner.py --all
              python tests/manual/runner.py --test t01_prereqs t03_pygame_display
              python tests/manual/runner.py --all --no-interactive
            """
        ),
    )
    parser.add_argument(
        "--list", action="store_true", help="List available tests and exit"
    )
    parser.add_argument("--all", action="store_true", help="Run all tests in order")
    parser.add_argument(
        "--test", nargs="+", metavar="STEM", help="Run specific tests by stem name"
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Skip tests that require human observation; auto-answer prompts",
    )

    args = parser.parse_args()

    if args.list:
        print("\nAvailable tests (in run order):\n")
        for stem in all_stems:
            try:
                mod = _load_module(stem)
                title = getattr(mod, "TITLE", "")
                interactive = getattr(mod, "INTERACTIVE", False)
                depends = getattr(mod, "DEPENDS", [])
                tag = " [interactive]" if interactive else ""
                dep_str = f"  (needs: {', '.join(depends)})" if depends else ""
                print(f"  {stem:<30} {title}{tag}{dep_str}")
            except Exception as exc:
                print(f"  {stem:<30} <load error: {exc}>")
        print()
        return

    if args.all:
        stems = all_stems
    elif args.test:
        stems = args.test
    else:
        parser.print_help()
        sys.exit(0)

    sys.exit(run_tests(stems, no_interactive=args.no_interactive))


if __name__ == "__main__":
    main()
