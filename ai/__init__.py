"""AI inference package for ElderLife AI.

Currently this package defines the **typed interfaces** every predictor must
implement, plus the error raised when no model is available. It contains **no
trained model and no training code**.

That distinction matters. The interfaces let the backend be written against a
stable contract today, while `ModelNotLoadedError` guarantees the system reports
"not available" instead of inventing a prediction.

See [`base.py`](base.py) for the result types, and the per-problem READMEs in
`fall_detection/`, `activity_recognition/` and `behavioral_analysis/` for what
each one will eventually do.
"""

from __future__ import annotations

from ai.base import (
    ActivityResult,
    AnomalyResult,
    FallDetectionResult,
    ModelInfo,
    ModelNotLoadedError,
    Predictor,
)

__all__ = [
    "ActivityResult",
    "AnomalyResult",
    "FallDetectionResult",
    "ModelInfo",
    "ModelNotLoadedError",
    "Predictor",
    "__version__",
]

# Version of the *interfaces*, not of any model. Bump this when a result type
# changes in a way callers must know about.
__version__ = "0.1.0"
