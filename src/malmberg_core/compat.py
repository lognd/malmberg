"""Python version compatibility shims."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

if sys.version_info < (3, 11):
    from typing_extensions import Self
else:
    from typing import Self

# tomllib is stdlib on 3.11+; fall back to tomli on older Python.
try:
    import tomllib as toml  # type: ignore[import-not-found,no-redef]
except ImportError:
    try:
        import tomli as toml  # type: ignore[import-not-found,no-redef]
    except ImportError:
        import toml  # type: ignore[import-not-found,no-redef]

# asyncio.TaskGroup was added in Python 3.11.
if sys.version_info >= (3, 11):
    from asyncio import TaskGroup as TaskGroup
else:

    class TaskGroup:
        """Minimal asyncio.TaskGroup backport for Python 3.10."""

        def __init__(self) -> None:
            self._tasks: list[asyncio.Task[Any]] = []

        async def __aenter__(self) -> "TaskGroup":
            return self

        async def __aexit__(
            self,
            exc_type: Any,
            exc_val: Any,
            exc_tb: Any,
        ) -> None:
            if not self._tasks:
                return
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException) and not isinstance(
                    r, asyncio.CancelledError
                ):
                    raise r

        def create_task(
            self, coro: Any, *, name: str | None = None
        ) -> asyncio.Task[Any]:
            task = asyncio.get_event_loop().create_task(coro, name=name)
            self._tasks.append(task)
            return task


__all__ = ["toml", "Self", "TaskGroup"]
