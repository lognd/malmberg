"""Server-side face detection, embedding, and person grouping.

Everything under this package is SERVER-ONLY: it is never imported by
malmberg_display, and its heavy ML dependencies (insightface, onnxruntime)
live in the optional `faces` extra -- never in the base dependency set --
so the Raspberry Pi display build stays free of them. Import is always
best-effort at call time; when the extra is not installed the package
degrades to "no faces detected" rather than raising.
"""

from __future__ import annotations
