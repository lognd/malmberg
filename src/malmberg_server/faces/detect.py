"""Best-effort face detection + embedding, server-only.

Uses insightface (see MODEL_PACK) on CPU via onnxruntime. Both are the
optional `faces` extra -- NEVER installed on the display/Pi. Mirrors the
lazy best-effort import pattern used by malmberg_server.ingest.media for
pillow-heif and reverse_geocoder: if the extra is missing, or model load or
inference fails for any reason, this module logs a warning and returns an
empty result rather than raising, so face detection is purely additive and
never blocks or breaks ingestion.

Low-quality faces are filtered out *before* they reach the clustering stage:
faces below MIN_DET_SCORE (detector confidence) or smaller than
MIN_FACE_AREA_FRAC of the image are dropped, since tiny/uncertain background
faces otherwise create spurious singleton "people" and mis-groupings.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from malmberg_core.logging import get_logger

_log = get_logger(__name__)

_MODEL_DIR_NAME = ".faces"
"""Subdirectory of fs_root where the insightface model pack is cached."""

MODEL_PACK = "buffalo_l"
"""insightface model pack: the larger RetinaFace detector + ArcFace embedder.

buffalo_l gives notably better embeddings than buffalo_s; the server is
x86_64 with CPU/RAM headroom (this never runs on the Pi). Downloaded once on
first use into the fs_root/.faces/models cache. A single constant so the pack
is trivial to change."""

_DET_SIZE = (640, 640)

MIN_DET_SCORE = 0.6
"""Drop detections below this detector confidence -- weak detections are a
major source of spurious singleton people."""

MIN_FACE_AREA_FRAC = 0.005
"""Drop faces whose bounding-box area is below this fraction of the image
area (i.e. tiny background faces), which cluster poorly and add noise."""


class FaceRecord(BaseModel):
    """One detected face: its bounding box, embedding, and detector score."""

    bbox: tuple[int, int, int, int]
    """(x1, y1, x2, y2) in source image pixel coordinates."""
    embedding: list[float]
    """L2-normalizable 512-d ArcFace embedding, used for cosine-similarity
    clustering in malmberg_server.faces.people."""
    det_score: float = 0.0
    """Detector confidence for this face."""


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
            name=MODEL_PACK,
            root=str(model_root),
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=_DET_SIZE)
        _analyzer = app
        _log.info("Loaded insightface model pack %r from %s", MODEL_PACK, model_root)
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
    worker does this. Faces below MIN_DET_SCORE or smaller than
    MIN_FACE_AREA_FRAC of the image are filtered out. Returns [] if the
    `faces` extra is not installed, the file cannot be decoded, or detection
    fails for any other reason -- this function never raises into its caller.
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
        img_h, img_w = img.shape[:2]
        img_area = float(img_w * img_h) or 1.0
        faces = analyzer.get(img)
        records = []
        for face in faces:
            det_score = float(getattr(face, "det_score", 0.0))
            if det_score < MIN_DET_SCORE:
                continue
            x1, y1, x2, y2 = (int(v) for v in face.bbox)
            area = max(0, x2 - x1) * max(0, y2 - y1)
            if area / img_area < MIN_FACE_AREA_FRAC:
                continue
            embedding = [float(v) for v in face.normed_embedding]
            records.append(
                FaceRecord(
                    bbox=(x1, y1, x2, y2), embedding=embedding, det_score=det_score
                )
            )
        return records
    except Exception:
        _log.warning("detect_faces failed for %s", image_path, exc_info=True)
        return []
