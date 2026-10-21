"""Registry of the AI predictors the backend can ask for.

Three problems are declared. One of them — fall detection — now has a real,
trained model behind it, and its predictor reports that honestly:

    >>> from ai.registry import get_predictor
    >>> predictor = get_predictor("fall_detection")
    >>> predictor.is_ready()   # True only if the trained model file is present
    True

The other two still have no model. They are `UnavailablePredictor` instances,
whose only job is to say so rather than to return a guess.

Two things the registry guarantees:

* a name that is not declared fails loudly with `KeyError`;
* a predictor with no model raises `ModelNotLoadedError`, which the API turns
  into an honest HTTP 503 instead of a fabricated prediction.
"""

from __future__ import annotations

from typing import Any

from ai.base import (
    ModelInfo,
    ModelNotLoadedError,
    Predictor,
    ResultKind,
)
from ai.fall_detection.predictor import FallDetectionPredictor

__all__ = [
    "AVAILABLE_PREDICTORS",
    "UnavailablePredictor",
    "get_predictor",
    "list_predictors",
]

#: The three problems this project set out to solve. The keys are the stable
#: identifiers used by the API and by `docs/`.
AVAILABLE_PREDICTORS: dict[str, ResultKind] = {
    "fall_detection": "fall_detection",
    "activity_recognition": "activity_recognition",
    "anomaly_detection": "anomaly_detection",
}

#: Which public research dataset each problem is trained on (or will be).
#: Recorded here so the API can state its provenance without reading the
#: dataset documentation at runtime. `fall_detection` uses SisFall because
#: UP-Fall's full distribution is ~812 GB — see docs/datasets/sisfall.md.
PLANNED_DATASETS: dict[str, str] = {
    "fall_detection": "SisFall",
    "activity_recognition": "UCI HAR",
    "anomaly_detection": "CASAS",
}


class UnavailablePredictor:
    """A predictor whose model has not been trained yet.

    Implements the `Predictor` protocol so callers can treat it exactly like a
    real predictor, and always raises `ModelNotLoadedError` from `predict()`.
    It never returns a made-up answer.
    """

    def __init__(self, name: str, kind: ResultKind) -> None:
        self._name = name
        self._kind = kind

    @property
    def info(self) -> ModelInfo:
        """Metadata describing a model that does not exist yet."""
        return ModelInfo(
            name=self._name,
            version="",
            kind=self._kind,
            trained_at=None,
            # Explicitly None: no model means no measured metrics. Putting
            # zeros or placeholders here would fabricate evaluation results.
            metrics=None,
            dataset=PLANNED_DATASETS.get(self._name),
        )

    def is_ready(self) -> bool:
        """Always False: no model file has been produced for this problem."""
        return False

    def predict(self, features: Any) -> Any:
        """Refuse to predict, rather than inventing a result."""
        raise ModelNotLoadedError(
            self._name,
            reason=(
                f"No trained model is available for {self._name!r} yet. "
                f"The planned dataset is {PLANNED_DATASETS.get(self._name, 'not decided')}. "
                "Train the model before calling this predictor."
            ),
        )


def get_predictor(name: str) -> Predictor:
    """Return the predictor registered for `name`.

    Fall detection has a trained model and returns a real predictor; whether it
    is *usable* still depends on the model file being present, which `is_ready()`
    reports. The other two return a placeholder that refuses to predict.

    Raises `KeyError` for an unknown name, so a typo fails loudly at the call
    site instead of silently returning a placeholder.
    """
    try:
        kind = AVAILABLE_PREDICTORS[name]
    except KeyError:
        raise KeyError(
            f"Unknown predictor {name!r}. Known predictors: "
            f"{sorted(AVAILABLE_PREDICTORS)}"
        ) from None

    if name == "fall_detection":
        return FallDetectionPredictor()

    return UnavailablePredictor(name, kind)


def list_predictors() -> list[dict[str, Any]]:
    """Describe every predictor and whether it is actually usable.

    This is what the API reports. For fall detection the entry now carries the
    real, measured metrics and a model version; the other two still report
    `is_ready: False` and no metrics, which is the truth rather than a
    placeholder.
    """
    described: list[dict[str, Any]] = []
    for name in AVAILABLE_PREDICTORS:
        predictor = get_predictor(name)
        info = predictor.info
        described.append(
            {
                "name": name,
                "is_ready": predictor.is_ready(),
                "model_version": info.version or None,
                "trained_at": info.trained_at,
                "metrics": info.metrics,
                "dataset": info.dataset,
            }
        )
    return described
