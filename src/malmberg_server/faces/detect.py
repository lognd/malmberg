"""Best-effort face detection + embedding, server-only.

Uses insightface (buffalo_s model pack) on CPU via onnxruntime. Both are the
optional `faces` extra -- NEVER installed on the display/Pi. Mirrors the
lazy best-effort import pattern used by malmberg_server.ingest.media for
pillow-heif and reverse_geocoder: if the extra is missing, or model load or
inference fails for any reason, this module logs a warning and returns an
empty result rather than raising, so face detection is purely additive and
never blocks or breaks ingestion.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from malmberg_core.logging import get_logger

_log = get_logger(__name__)

_MODEL_DIR_NAME = ".faces"
"""Subdirectory of fs_root where the insightface model pack is cached."""

_MODEL_PACK = "buffalo_s"
"""Small insightface model pack: RetinaFace detector + a 512-d ArcFace embedder."""

_SIM_MATCH_DET_SIZE = (640, 640)


class FaceRecord(BaseModel):
    """One detected face: its bounding box and 512-d embedding."""

    bbox: tuple[int, int, int, int]
    """(x1, y1, x2, y2) in source image pixel coordinates."""
    embedding: list[float]
    """L2-normalizable 512-d ArcFace embedding, used for cosine-similarity
    clustering in malmberg_server.faces.people."""


_analyzer = None
"""Lazily-constructed insightface.app.FaceAnalysis singleton, or False once
construction has been attempted and failed. None means "not yet attempted".
Loaded once and reused across calls -- model load is expensive."""


def _get_analyzer(model_root: Path):
    """Return the shared FaceAnalysis instance, constructing it on first use.

    Returns None if the `faces` extra is not installed or construction
    fails for any reason (logged); never raises.
    """
    global _analyzer
    if _analyzer is False:
        return None
    if _analyzer is not None:
        return _analyzer
    try:
        from insightface.app import FaceAnalysis
    except ImportError:
        _log.warning(
            "insightface unavailable; face detection disabled (install the "
            "'faces' extra on the server: uv sync --extra faces)"
        )
        _analyzer = False
        return None
    try:
        model_root.mkdir(parents=True, exist_ok=True)
        app = FaceAnalysis(
            name=_MODEL_PACK,
            root=str(model_root),
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=_SIM_MATCH_DET_SIZE)
        _analyzer = app
        _log.info("Loaded insightface model pack %r from %s", _MODEL_PACK, model_root)
        return _analyzer
    except Exception:
        _log.warning("Failed to load insightface model pack", exc_info=True)
        _analyzer = False
        return None


def detect_faces(image_path: Path, model_root: Path) -> list[FaceRecord]:
    """Detect faces and their embeddings in *image_path*.

    *model_root* is the directory the model pack is cached under (typically
    fs_root/.faces/models). Runs synchronously (CPU-bound) -- callers on the
    async request path MUST invoke this via a thread executor
    (run_in_executor), never inline in an async handler; the background face
    worker does this. Returns [] if the `faces` extra is not installed, the
    file cannot be decoded, or detection fails for any other reason -- this
    function is never allowed to raise into its caller.
    """
    analyzer = _get_analyzer(model_root)
    if analyzer is None:
        return []
    try:
        import cv2  # bundled with insightface's opencv-python-headless dep

        img = cv2.imread(str(image_path))
        if img is None:
            _log.warning("detect_faces: could not decode %s", image_path)
            return []
        faces = analyzer.get(img)
        records = []
        for face in faces:
            x1, y1, x2, y2 = (int(v) for v in face.bbox)
            embedding = [float(v) for v in face.normed_embedding]
            records.append(FaceRecord(bbox=(x1, y1, x2, y2), embedding=embedding))
        return records
    except Exception:
        _log.warning("detect_faces failed for %s", image_path, exc_info=True)
        return []
