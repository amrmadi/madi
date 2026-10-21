"""Typed inference interfaces shared by every AI module in `ai/`.

Why this file exists
--------------------
The three AI problems (fall detection, activity recognition, behavioural
anomaly detection) are developed separately and will eventually load different
kinds of trained model. Without a shared contract, each one would invent its
own return shape, and the backend would need three different integration paths.

Instead, every predictor in this package returns one of the dataclasses below.
They are deliberately plain `dataclasses` with no third-party dependency, so
this file imports with nothing installed — including in a test run that must
not download a dataset or reach the network.

What these types are NOT
------------------------
**Defining these types does not mean any model exists.** No dataset has been
downloaded and no model has been trained. Every factory function here raises
`ModelNotLoadedError`, and the backend turns that into an honest HTTP 503
rather than a made-up prediction.

Two rules the types enforce, matching the project's honesty requirements:

1. **Simulated input can never be reported as a real measurement.** A result
   derived from `source="simulated"` must carry `is_simulated=True`, so the UI
   is forced to label it as demo data.
2. **A predictor with no model must say so**, rather than returning a guess.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

__all__ = [
    "ActivityName",
    "ActivityResult",
    "AnomalyResult",
    "EventSourceName",
    "FallDetectionResult",
    "ModelInfo",
    "ModelNotLoadedError",
    "Predictor",
    "ResultKind",
]


# ---------------------------------------------------------------------------
# Literal vocabularies
# ---------------------------------------------------------------------------
# These mirror `backend/app/models/enums.py` deliberately as plain literals
# rather than importing backend code. The AI package must stay importable
# without a database driver, and a static type checker still catches typos.

ActivityName = Literal[
    "walking",
    "standing",
    "sitting",
    "lying",
    "eating",
    "sleeping",
    "toileting",
    "unknown",
]

EventSourceName = Literal[
    "simulated",
    "sensor",
    "manual_entry",
    "imported_dataset",
    "model",
]

# Which of the three problems a result belongs to.
ResultKind = Literal["fall_detection", "activity_recognition", "anomaly_detection"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ModelNotLoadedError(RuntimeError):
    """Raised when a predictor is asked to work without a trained model.

    This is the honest alternative to returning a fabricated prediction. Callers
    should surface it as HTTP 503 (`SERVICE_UNAVAILABLE`) — the service is
    reachable, but the capability genuinely is not available yet.
    """

    def __init__(self, model_name: str, *, reason: str | None = None) -> None:
        self.model_name = model_name
        self.reason = reason or (
            "No trained model file is available. Train the model first, or call "
            "this endpoint once a model has been produced."
        )
        super().__init__(f"{model_name} is not loaded: {self.reason}")


# ---------------------------------------------------------------------------
# Result base
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BaseResult:
    """Shared fields on every inference result.

    Frozen so a caller cannot quietly mutate a prediction after the fact —
    a result is a record of what the model said, and should stay that way.
    """

    #: Identifier of the model that produced this result, e.g. "fall-rf-v1".
    #: Empty string means the result did not come from a trained model.
    model_version: str

    #: Where the underlying data came from. Drives the honesty rule below.
    source: EventSourceName = "simulated"

    #: Human-readable explanation of *why* the model answered this way.
    #: Required: an unexplained prediction is not usable in a care setting.
    explanation: str = ""

    #: Extra detail (feature contributions, thresholds, raw scores, ...).
    #: Kept open-ended so a model can expose more without breaking callers.
    details: dict[str, Any] = field(default_factory=dict)

    #: The kind of problem this result answers. Set by each subclass.
    kind: ClassVar[ResultKind]

    def __post_init__(self) -> None:
        if not self.model_version:
            raise ValueError(
                "model_version must be set. A result that cannot name its model "
                "cannot be audited or reproduced."
            )

    @property
    def is_simulated(self) -> bool:
        """True when the input was not a real measurement.

        `simulated` (demo data) and `imported_dataset` (public research data
        recorded from other people) are both *not* measurements of this
        resident. Treating either as a live reading would be misleading.
        """
        return self.source in ("simulated", "imported_dataset")

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON responses and logging."""
        payload = dataclasses.asdict(self)
        payload["kind"] = self.kind
        payload["is_simulated"] = self.is_simulated
        return payload


# ---------------------------------------------------------------------------
# Fall detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallDetectionResult(_BaseResult):
    """The answer to "is this a fall?".

    `confidence` is the model's own probability, and is **not** a medical
    assessment. A high-confidence fall still requires a human to verify it;
    medical risk is a separate, validated concept.
    """

    kind: ClassVar[ResultKind] = "fall_detection"

    #: True when the model believes a fall occurred.
    is_fall: bool = False

    #: Model probability for the positive class, 0.0–1.0.
    confidence: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence!r}."
            )

    @property
    def needs_human_review(self) -> bool:
        """True when the result should be looked at by a person.

        Any positive prediction needs review. A model that claims certainty
        about a fall is exactly the case where a human check matters most.
        """
        return self.is_fall


# ---------------------------------------------------------------------------
# Activity recognition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivityResult(_BaseResult):
    """The answer to "what activity is happening?".

    `activity` is the top class; `scores` holds the full distribution when the
    model provides one. Keeping the whole distribution matters because "60 %
    walking, 38 % standing" is a very different situation from "99 % walking".
    """

    kind: ClassVar[ResultKind] = "activity_recognition"

    #: The most likely activity.
    activity: ActivityName = "unknown"

    #: Probability of `activity`, 0.0–1.0.
    confidence: float = 0.0

    #: Full per-class probability distribution, when available.
    scores: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence!r}."
            )
        for name, score in self.scores.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"score for {name!r} must be between 0.0 and 1.0, got {score!r}."
                )

    @property
    def is_ambiguous(self) -> bool:
        """True when the two best activities are close together.

        Used to avoid presenting a confident-looking label when the model was
        actually undecided. Returns False when no distribution was supplied.
        """
        if len(self.scores) < 2:
            return False
        ordered = sorted(self.scores.values(), reverse=True)
        return (ordered[0] - ordered[1]) < 0.10


# ---------------------------------------------------------------------------
# Behavioural anomaly detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnomalyResult(_BaseResult):
    """The answer to "is today's routine unusual for this person?".

    Deliberately **not** framed as "something is wrong". A routine change is
    frequently benign, so this result carries `deviation_score` plus the
    features that moved, and nothing resembling a diagnosis.
    """

    kind: ClassVar[ResultKind] = "anomaly_detection"

    #: True when the behaviour departs from the person's own baseline.
    is_anomaly: bool = False

    #: Dimensionless deviation from baseline. Higher means further from normal.
    #: The scale is model-defined and is documented by the producing model,
    #: not assumed here.
    deviation_score: float = 0.0

    #: Only deviations the model considers *more* than normal count as
    #: anomalous by default: an unusually quiet day can matter as much as an
    #: unusually busy one, so the direction is recorded explicitly rather than
    #: inferred from the sign of the score.
    direction: Literal["above", "below", "none"] = "none"

    #: Which baseline features deviated, and by how much. This is the
    #: explainability payload: a caregiver should be able to see *what* changed.
    deviating_features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.direction == "none" and self.deviating_features:
            raise ValueError(
                "direction is 'none' but deviating_features is non-empty. "
                "State which way the behaviour moved, or omit the features."
            )


# ---------------------------------------------------------------------------
# Predictor protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelInfo:
    """Metadata describing a trained model.

    Mirrors the `model_runs` table so the API can report what is loaded without
    reading the database inside the AI layer.
    """

    name: str
    version: str
    kind: ResultKind
    trained_at: str | None = None
    #: Evaluation metrics **as actually measured**, or None when the model has
    #: not been evaluated. Never fill this with placeholder numbers.
    metrics: dict[str, float] | None = None
    #: The dataset the model was trained on, for honest reporting.
    dataset: str | None = None


@runtime_checkable
class Predictor(Protocol):
    """The shape every predictor in this package implements.

    The backend depends on this protocol rather than on concrete classes, so a
    real model can be swapped in later without touching the API layer.
    """

    @property
    def info(self) -> ModelInfo:
        """Metadata about the loaded model."""
        ...

    def is_ready(self) -> bool:
        """True when a trained model is loaded and able to predict."""
        ...

    def predict(self, features: Any) -> _BaseResult:
        """Run inference.

        Must raise `ModelNotLoadedError` when `is_ready()` is False, rather
        than returning a placeholder result.
        """
        ...
