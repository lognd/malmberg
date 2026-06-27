"""Probabilistic snapshot retention policy.

Algorithm
---------
Given a list of *n_keep* retention slots and an ordered list of snapshot
names (oldest first), ``compute_deletions`` returns the names that should be
deleted to bring the list within policy.

Retention logic:

1. Always keep the *n_keep* most-recent snapshots unconditionally.
2. For older snapshots beyond that window, apply probabilistic halving:
   each snapshot that is *k* positions beyond the window has a
   ``0.5 ** k`` probability of being kept.  The decision is deterministic
   per snapshot name (hash-based) so that re-running the function on the
   same list produces the same result.

The net effect is an exponential back-off: snapshots from one day ago are
kept with probability 0.5, two days ago 0.25, and so on.  This gives a
logarithmic coverage of history while bounding storage growth.
"""

from __future__ import annotations

import hashlib
import math


def compute_deletions(snapshots: list[str], n_keep: int) -> list[str]:
    """Return snapshot names that should be deleted under the retention policy.

    Parameters
    ----------
    snapshots:
        All existing snapshot names, ordered oldest-first.
    n_keep:
        Number of recent snapshots to keep unconditionally.  Must be >= 1.

    Returns
    -------
    list[str]
        Subset of *snapshots* that should be deleted (may be empty).
    """
    if n_keep < 1:
        raise ValueError("n_keep must be >= 1")

    if len(snapshots) <= n_keep:
        return []

    unconditional = set(snapshots[-n_keep:])
    candidates = snapshots[: len(snapshots) - n_keep]

    to_delete: list[str] = []
    for i, name in enumerate(reversed(candidates)):
        k = i + 1
        threshold = math.pow(0.5, k)
        digest = int(hashlib.sha1(name.encode()).hexdigest(), 16)
        sample = (digest % 1_000_000) / 1_000_000.0
        if sample >= threshold and name not in unconditional:
            to_delete.append(name)

    return to_delete
