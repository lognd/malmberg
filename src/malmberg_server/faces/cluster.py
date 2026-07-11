"""Pure-Python face-embedding clustering primitives (no numpy dependency).

These functions operate on plain lists of floats so they are fully testable
without the `faces` extra installed (numpy/onnxruntime are never imported
here). The library is personal-scale (hundreds of faces), so an O(n^2)
pairwise pass is more than fast enough and keeps the code dependency-free.

Design notes on recognition quality (see the faces design doc):
- ArcFace embeddings from insightface are L2-normalized, so cosine
  similarity is the natural metric.
- Same-person cosine similarity for buffalo_l typically lands ~0.35-0.5
  across pose/lighting; `SIMILARITY_THRESHOLD` is tuned to the low-middle of
  that band to prefer grouping (fewer spurious singletons) over splitting.
- Online assignment compares a new face to the BEST (max) similarity among a
  candidate person's stored faces (single-linkage), not a drifting
  running-average centroid -- max-linkage tracks a person across varied
  shots far better and is not order-dependent per comparison.
- `connected_components` gives an order-independent, full re-cluster of the
  whole per-face graph (single-linkage / DBSCAN-with-minPts-1 equivalent).
"""

from __future__ import annotations

import math

SIMILARITY_THRESHOLD = 0.4
"""Minimum cosine similarity for two faces to be considered the same person.

Tuned for buffalo_l L2-normalized ArcFace embeddings (same-person pairs
typically >= ~0.4). Lower than the previous 0.5 centroid threshold because
that value over-split people across pose/lighting. A named constant so it is
trivial to re-tune; changing it takes effect on the existing library via the
worker's reprocess/recluster self-heal path."""


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of *a* and *b*, or -1.0 if not comparable."""
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return -1.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def max_similarity(embedding: list[float], candidates: list[list[float]]) -> float:
    """Return the highest cosine similarity between *embedding* and *candidates*.

    Returns -1.0 if there are no candidates. This is the single-linkage score
    used for online assignment: a face joins the person it is most similar to
    by any one of that person's stored faces.
    """
    best = -1.0
    for cand in candidates:
        sim = cosine_similarity(embedding, cand)
        if sim > best:
            best = sim
    return best


def centroid(embeddings: list[list[float]]) -> list[float]:
    """Return the element-wise mean of *embeddings*, or [] if empty."""
    if not embeddings:
        return []
    dim = len(embeddings[0])
    acc = [0.0] * dim
    for emb in embeddings:
        for i in range(dim):
            acc[i] += emb[i]
    n = len(embeddings)
    return [v / n for v in acc]


def connected_components(
    embeddings: list[list[float]], threshold: float = SIMILARITY_THRESHOLD
) -> list[list[int]]:
    """Single-linkage cluster *embeddings*, returning groups of indices.

    Builds a graph with an edge between any two faces whose cosine similarity
    is at least *threshold*, then returns the connected components (each a
    list of original indices). Order-independent: the grouping does not depend
    on the order faces were seen, unlike online assignment. O(n^2) pairwise,
    which is fine at personal-library scale.
    """
    n = len(embeddings)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(n):
        for j in range(i + 1, n):
            if cosine_similarity(embeddings[i], embeddings[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())
