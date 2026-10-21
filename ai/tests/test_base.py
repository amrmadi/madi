"""Tests for the result types in `ai/base.py` and the honesty rules they enforce.

Why these tests exist
---------------------
`ai/base.py` is the contract every predictor in this project fulfils, and it
encodes three of the project's honesty rules *in the type system*:

1. a result must name the model that produced it;
2. a result derived from something that is not a live measurement must say so
   (`is_simulated`);
3. an out-of-range number is a programming error, not a value to be stored.

Those rules are only worth anything if they are enforced, so they are tested
here rather than left to a code review.
"""

from __future__ import annotations

import pytest

from ai.base import (
    ActivityResult,
    AnomalyResult,
    FallDetectionResult,
    ModelInfo,
    ModelNotLoadedError,
)


# ---------------------------------------------------------------------------
# model_version
# ---------------------------------------------------------------------------


def test_result_without_a_model_version_is_rejected() -> None:
    """A result that cannot name its model cannot be audited or reproduced."""
    with pytest.raises(ValueError):
        FallDetectionResult(model_version="", confidence=0.5)

    with pytest.raises(ValueError):
        ActivityResult(model_version="", activity="walking")

    with pytest.raises(ValueError):
        AnomalyResult(model_version="", deviation_score=1.0)


# ---------------------------------------------------------------------------
# is_simulated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    ["simulated", "imported_dataset"],
)
def test_simulated_sources_are_flagged_as_simulated(source: str) -> None:
    """Demo data and research data are both *not* a resident's own reading."""
    result = FallDetectionResult(model_version="fall-rf-v1", source=source)
    assert result.is_simulated is True


@pytest.mark.parametrize("source", ["sensor", "manual_entry", "model"])
def test_real_sources_are_not_flagged_as_simulated(source: str) -> None:
    """A live sensor reading is a real measurement and must not be flagged."""
    result = FallDetectionResult(model_version="fall-rf-v1", source=source)
    assert result.is_simulated is False


# ---------------------------------------------------------------------------
# confidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0, -1.0])
def test_fall_detection_confidence_must_be_a_probability(confidence: float) -> None:
    with pytest.raises(ValueError):
        FallDetectionResult(model_version="fall-rf-v1", confidence=confidence)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0, -1.0])
def test_activity_confidence_must_be_a_probability(confidence: float) -> None:
    with pytest.raises(ValueError):
        ActivityResult(model_version="har-rf-v1", confidence=confidence)


def test_confidence_bounds_are_inclusive() -> None:
    """0.0 and 1.0 are valid probabilities and must be accepted."""
    assert FallDetectionResult(model_version="fall-rf-v1", confidence=0.0).confidence == 0.0
    assert FallDetectionResult(model_version="fall-rf-v1", confidence=1.0).confidence == 1.0


# ---------------------------------------------------------------------------
# activity scores
# ---------------------------------------------------------------------------


def test_activity_scores_must_be_probabilities() -> None:
    with pytest.raises(ValueError):
        ActivityResult(
            model_version="har-rf-v1",
            activity="walking",
            scores={"walking": 0.7, "standing": 1.4},
        )


def test_activity_scores_accept_the_full_probability_range() -> None:
    result = ActivityResult(
        model_version="har-rf-v1",
        activity="walking",
        scores={"walking": 0.0, "standing": 1.0},
    )
    assert result.scores["walking"] == 0.0
    assert result.scores["standing"] == 1.0


# ---------------------------------------------------------------------------
# is_ambiguous
# ---------------------------------------------------------------------------


def test_activity_without_a_distribution_is_not_ambiguous() -> None:
    """A single score says nothing about how close the runner-up was."""
    result = ActivityResult(model_version="har-rf-v1", activity="walking", scores={"walking": 0.8})
    assert result.is_ambiguous is False


def test_activity_with_no_scores_is_not_ambiguous() -> None:
    result = ActivityResult(model_version="har-rf-v1", activity="walking")
    assert result.scores == {}
    assert result.is_ambiguous is False


def test_activity_is_ambiguous_when_the_top_two_are_close() -> None:
    """Two classes within 0.10 of each other mean the model was undecided."""
    result = ActivityResult(
        model_version="har-rf-v1",
        activity="walking",
        scores={"walking": 0.52, "standing": 0.47},
    )
    assert result.is_ambiguous is True


def test_activity_is_not_ambiguous_when_the_top_two_are_far_apart() -> None:
    result = ActivityResult(
        model_version="har-rf-v1",
        activity="walking",
        scores={"walking": 0.95, "standing": 0.05},
    )
    assert result.is_ambiguous is False


def test_ambiguity_boundary_is_just_above_one_tenth() -> None:
    """A gap of 0.10 or more is a decision, not a tie.

    The exact-0.10 case is not asserted: 0.1 has no exact binary
    representation, so a pair such as 0.6/0.5 lands just under the threshold
    in floating point. The values here sit clearly on the "not ambiguous"
    side of it.
    """
    at_or_above = ActivityResult(
        model_version="har-rf-v1",
        activity="walking",
        scores={"walking": 0.80, "standing": 0.70},
    )
    assert at_or_above.is_ambiguous is False

    just_under = ActivityResult(
        model_version="har-rf-v1",
        activity="walking",
        scores={"walking": 0.599, "standing": 0.500},
    )
    assert just_under.is_ambiguous is True


# ---------------------------------------------------------------------------
# needs_human_review
# ---------------------------------------------------------------------------


def test_a_positive_fall_needs_human_review() -> None:
    result = FallDetectionResult(
        model_version="fall-rf-v1", is_fall=True, confidence=0.91
    )
    assert result.needs_human_review is True


def test_a_negative_fall_does_not_need_human_review() -> None:
    result = FallDetectionResult(
        model_version="fall-rf-v1", is_fall=False, confidence=0.08
    )
    assert result.needs_human_review is False


# ---------------------------------------------------------------------------
# anomaly direction
# ---------------------------------------------------------------------------


def test_direction_none_with_deviating_features_is_rejected() -> None:
    """Saying 'nothing moved' while listing what moved is contradictory."""
    with pytest.raises(ValueError):
        AnomalyResult(
            model_version="anomaly-if-v1",
            deviation_score=2.0,
            direction="none",
            deviating_features={"morning_walk_count": 3.0},
        )


def test_direction_none_without_deviating_features_is_allowed() -> None:
    result = AnomalyResult(
        model_version="anomaly-if-v1", deviation_score=0.1, direction="none"
    )
    assert result.deviating_features == {}


@pytest.mark.parametrize("direction", ["above", "below"])
def test_a_directional_anomaly_may_list_deviating_features(direction: str) -> None:
    result = AnomalyResult(
        model_version="anomaly-if-v1",
        deviation_score=2.0,
        direction=direction,
        deviating_features={"morning_walk_count": 3.0},
    )
    assert result.direction == direction
    assert result.deviating_features == {"morning_walk_count": 3.0}


# ---------------------------------------------------------------------------
# as_dict
# ---------------------------------------------------------------------------


def test_as_dict_carries_the_kind_and_the_simulation_flag() -> None:
    """The API serialises results with `as_dict`, so both keys must be there."""
    result = FallDetectionResult(
        model_version="fall-rf-v1", source="imported_dataset", confidence=0.5
    )
    payload = result.as_dict()
    assert payload["kind"] == "fall_detection"
    assert payload["is_simulated"] is True


def test_as_dict_uses_the_subclass_kind_for_every_result_type() -> None:
    assert ActivityResult(model_version="har-rf-v1").as_dict()["kind"] == (
        "activity_recognition"
    )
    assert AnomalyResult(model_version="anomaly-if-v1").as_dict()["kind"] == (
        "anomaly_detection"
    )


# ---------------------------------------------------------------------------
# ModelNotLoadedError
# ---------------------------------------------------------------------------


def test_model_not_loaded_error_names_the_model_and_the_reason() -> None:
    """The API puts this message in front of a user; it has to be useful."""
    error = ModelNotLoadedError("activity_recognition", reason="No model file yet.")
    message = str(error)
    assert "activity_recognition" in message
    assert "No model file yet." in message
    assert error.model_name == "activity_recognition"
    assert error.reason == "No model file yet."


def test_model_not_loaded_error_has_a_default_reason() -> None:
    """Even without an explicit reason the message must still name the model."""
    error = ModelNotLoadedError("fall_detection")
    assert "fall_detection" in str(error)
    assert error.reason


# ---------------------------------------------------------------------------
# ModelInfo
# ---------------------------------------------------------------------------


def test_model_info_may_have_no_metrics() -> None:
    """A model that has not been evaluated reports None, not zeros."""
    info = ModelInfo(
        name="activity_recognition",
        version="",
        kind="activity_recognition",
        dataset="UCI HAR",
    )
    assert info.metrics is None
    assert info.trained_at is None
    assert info.version == ""
