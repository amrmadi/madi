"""SisFall fall-detection predictor: the trained baseline behind the API.

How it fits the rest of the project
-----------------------------------
`ai/base.py` defines the contract; `ai/registry.py` hands the backend a
predictor by name. This module is the concrete implementation for
`"fall_detection"`, and it is the **only** place that knows how to turn
accelerometer samples into a `FallDetectionResult`.

Design rules it follows, and why
--------------------------------
* **It never guesses.** If the model file is absent, `is_ready()` returns False
  and `predict()` raises `ModelNotLoadedError`, which the API already turns into
  an honest HTTP 503. A placeholder answer would be worse than no answer.
* **It reuses the training-time pipeline.** Windows, feature order and the
  scaler come from the same `preprocess` module the training script used, so
  serving cannot silently drift from training.
* **It records provenance.** `source="imported_dataset"` is used for SisFall
  input, which makes `is_simulated` True: this data was recorded from unrelated
  volunteers, so it must never be presented as a resident's own reading.
* **It loads lazily.** Importing this module does nothing expensive. The joblib
  file is 80+ MB and is only read on first use, so the backend starts fast and
  the test suite does not pay for a model it may not touch.
* **No HTTP, no database.** The AI package stays a pure library.

Honesty about what the numbers mean
-----------------------------------
`metrics` are the values actually measured by `train.py`, reproduced verbatim.
The elderly figure comes from falls performed by a **single** subject; it is
carried in `details`/`caveats`, not hidden. A predicted fall is a prompt for a
human to check, never a medical conclusion.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import numpy as np

from ai.base import FallDetectionResult, ModelInfo, ModelNotLoadedError
from ai.fall_detection import preprocess as pp

__all__ = ["FallDetectionPredictor", "build_predictor"]

#: Default location of the trained artefacts (git-ignored).
DEFAULT_MODEL_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "models" / "fall_detection"
)
DEFAULT_MODEL_VERSION = "fall-rf-v1"


class FallDetectionPredictor:
    """Loads the trained RandomForest and answers "is this a fall?".

    Satisfies the `Predictor` protocol in `ai/base.py`.
    """

    def __init__(
        self,
        model_version: str = DEFAULT_MODEL_VERSION,
        model_dir: str | pathlib.Path = DEFAULT_MODEL_DIR,
    ) -> None:
        self._model_version = model_version
        self._model_dir = pathlib.Path(model_dir)
        # Loaded lazily on first use; see the module docstring.
        self._artefacts: dict[str, Any] | None = None
        self._load_error: str | None = None

    # -- loading ------------------------------------------------------------

    @property
    def _joblib_path(self) -> pathlib.Path:
        return self._model_dir / f"{self._model_version}.joblib"

    @property
    def _json_path(self) -> pathlib.Path:
        return self._model_dir / f"{self._model_version}.json"

    def _load(self) -> dict[str, Any] | None:
        """Load the artefacts once. Returns None (and records why) on failure."""
        if self._artefacts is not None:
            return self._artefacts
        if self._load_error is not None:
            return None

        if not self._joblib_path.exists():
            self._load_error = (
                f"Model file not found at {self._joblib_path}. Train it with "
                "'python -m ai.fall_detection.train'."
            )
            return None

        try:
            import joblib

            self._artefacts = joblib.load(self._joblib_path)
        except Exception as exc:  # pragma: no cover - depends on local artefacts
            self._load_error = f"Failed to load model file: {exc}"
            return None
        return self._artefacts

    def is_ready(self) -> bool:
        """True only when the trained model file is present and loadable."""
        return self._load() is not None

    def _metadata(self) -> dict[str, Any]:
        """Readable JSON metadata, so metrics can be shown without unpickling."""
        if not self._json_path.exists():
            return {}
        try:
            return json.loads(self._json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    # -- description --------------------------------------------------------

    @property
    def info(self) -> ModelInfo:
        """Metadata about the loaded model, using **measured** metrics only."""
        artefacts = self._load()
        if artefacts is None:
            return ModelInfo(
                name="fall_detection",
                version="",
                kind="fall_detection",
                trained_at=None,
                metrics=None,
                dataset="SisFall",
            )

        metadata = artefacts.get("metadata") or self._metadata()
        metrics = artefacts.get("metrics") or metadata.get("metrics")
        return ModelInfo(
            name="fall_detection",
            version=str(artefacts.get("model_version", self._model_version)),
            kind="fall_detection",
            trained_at=metadata.get("trained_at"),
            # Already floats from the real training run; never placeholders.
            metrics={k: float(v) for k, v in (metrics or {}).items()} or None,
            dataset=artefacts.get("dataset", "SisFall"),
        )

    # -- inference ----------------------------------------------------------

    def predict(self, features: Any) -> FallDetectionResult:
        """Classify a window of accelerometer samples.

        `features` must be an `(n, 3)` array of **accelerometer samples in g**,
        long enough for one window (2 s at 200 Hz = 400 rows by default).
        Accepts a list of rows or a numpy array.

        Raises `ModelNotLoadedError` when no model is loaded, rather than
        returning a made-up prediction.
        """
        artefacts = self._load()
        if artefacts is None:
            raise ModelNotLoadedError("fall_detection", reason=self._load_error)

        samples = self._as_sample_matrix(features)
        window_rows = int(artefacts.get("window_rows", pp.DEFAULT_WINDOW_ROWS))
        if samples.shape[0] < window_rows:
            raise ValueError(
                f"Need at least {window_rows} samples for one window "
                f"({window_rows / pp.SAMPLE_RATE_HZ:.1f}s at {pp.SAMPLE_RATE_HZ} Hz); "
                f"got {samples.shape[0]}. Pass a longer sequence, or a "
                "'preprocessed' feature dict produced by windowing first."
            )

        # Use the final full window of the sequence: in a real stream the most
        # recent data is the part that matters.
        latest = samples[-window_rows:]
        window = pp.Window(
            subject="unknown",
            cohort="unknown",
            code="live",
            run="00",
            label=-1,
            start_row=int(samples.shape[0] - window_rows),
            features=pp.extract_features(latest),
        )
        return self._classify_windows(artefacts, [window])[0]

    def predict_windows(self, windows: list[pp.Window]) -> list[FallDetectionResult]:
        """Classify already-windowed features, in one batched pass.

        Exposed because evaluation and a streaming caller both want to score
        many windows without paying the per-call overhead.
        """
        artefacts = self._load()
        if artefacts is None:
            raise ModelNotLoadedError("fall_detection", reason=self._load_error)
        return self._classify_windows(artefacts, windows)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _as_sample_matrix(features: Any) -> np.ndarray:
        """Coerce input into an `(n, 3)` float array, failing loudly if not."""
        if isinstance(features, np.ndarray):
            array = features.astype(np.float64, copy=False)
        else:
            try:
                array = np.asarray(features, dtype=np.float64)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "features must be an (n, 3) array of accelerometer samples in g."
                ) from exc

        if array.ndim != 2 or array.shape[1] != 3:
            raise ValueError(
                f"features must have shape (n, 3) in units of g, got {array.shape!r}."
            )
        return array

    def _classify_windows(
        self, artefacts: dict[str, Any], windows: list[pp.Window]
    ) -> list[FallDetectionResult]:
        if not windows:
            return []

        model = artefacts["model"]
        scaler_meta = artefacts["scaler"]
        names = list(artefacts["feature_names"])
        threshold = float(artefacts.get("threshold", 0.5))
        version = str(artefacts.get("model_version", self._model_version))

        raw = np.asarray(
            [[w.features[name] for name in names] for w in windows], dtype=np.float64
        )

        # Rebuild the scaler exactly as it was fitted (train-only statistics).
        mean = np.asarray(scaler_meta["mean"], dtype=np.float64)
        scale = np.asarray(scaler_meta["scale"], dtype=np.float64)
        scaled = (raw - mean) / scale

        probabilities = np.asarray(model.predict_proba(scaled))[:, 1]

        results: list[FallDetectionResult] = []
        for window, probability in zip(windows, probabilities, strict=True):
            confidence = float(probability)
            is_fall = bool(confidence >= threshold)
            results.append(
                FallDetectionResult(
                    model_version=version,
                    source="imported_dataset",
                    is_fall=is_fall,
                    confidence=confidence,
                    explanation=self._explain(window, confidence, threshold),
                    details={
                        "threshold": threshold,
                        "code": window.code,
                        "window_rows": int(artefacts.get("window_rows", pp.DEFAULT_WINDOW_ROWS)),
                        "sample_rate_hz": int(artefacts.get("sample_rate_hz", pp.SAMPLE_RATE_HZ)),
                        "not_a_medical_assessment": True,
                    },
                )
            )
        return results

    @staticmethod
    def _explain(window: pp.Window, confidence: float, threshold: float) -> str:
        side = "at or above" if confidence >= threshold else "below"
        return (
            f"Model probability {confidence:.2f} is {side} the operating threshold "
            f"{threshold:.2f}. Peak magnitude in the window was "
            f"{window.features.get('mag_max', 0.0):.2f} g. This is a "
            "detection prompt requiring human verification, not a medical finding."
        )


def build_predictor() -> FallDetectionPredictor:
    """Factory used by the registry, so the registry holds no model paths."""
    return FallDetectionPredictor()
