"""Tests for `ai/registry.py` — the map from a capability name to a predictor.

What the registry promises
--------------------------
* An unknown name fails **loudly** with a `KeyError` that lists the names
  that do exist, so a typo is caught at the call site instead of silently
  receiving a placeholder.
* A capability with no model reports itself as unavailable:
  `is_ready() is False`, `info.metrics is None`, and `predict()` raises
  `ModelNotLoadedError`. It never returns a made-up answer.

These are the rules the API relies on when it turns a missing model into an
honest `503 MODEL_NOT_LOADED`, so they are tested directly.
"""

from __future__ import annotations

import pathlib

import pytest

from ai.base import ModelNotLoadedError
from ai.fall_detection.predictor import (
    DEFAULT_MODEL_DIR,
    DEFAULT_MODEL_VERSION,
    FallDetectionPredictor,
)
from ai.registry import AVAILABLE_PREDICTORS, get_predictor, list_predictors


def _fall_model_path() -> pathlib.Path:
    """Where the fall-detection artefacts would be, if they had been trained."""
    return pathlib.Path(DEFAULT_MODEL_DIR) / f"{DEFAULT_MODEL_VERSION}.joblib"


# ---------------------------------------------------------------------------
# Unknown names
# ---------------------------------------------------------------------------


def test_an_unknown_predictor_name_raises_key_error() -> None:
    """A typo must fail at the call site, not return a placeholder."""
    with pytest.raises(KeyError):
        get_predictor("does_not_exist")


def test_the_key_error_lists_the_known_predictors() -> None:
    """The error message has to tell the caller what the real names are."""
    with pytest.raises(KeyError) as excinfo:
        get_predictor("does_not_exist")

    message = str(excinfo.value)
    for name in AVAILABLE_PREDICTORS:
        assert name in message


# ---------------------------------------------------------------------------
# The capabilities that have no model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["activity_recognition", "anomaly_detection"])
def test_an_untrained_predictor_is_not_ready(name: str) -> None:
    predictor = get_predictor(name)
    assert predictor.is_ready() is False


@pytest.mark.parametrize("name", ["activity_recognition", "anomaly_detection"])
def test_an_untrained_predictor_reports_no_metrics(name: str) -> None:
    """No model means no measured metrics. Zeros here would be a fabrication."""
    predictor = get_predictor(name)
    assert predictor.info.metrics is None
    assert predictor.info.version == ""
    assert predictor.info.trained_at is None


@pytest.mark.parametrize("name", ["activity_recognition", "anomaly_detection"])
def test_an_untrained_predictor_refuses_to_predict(name: str) -> None:
    """This is the error the API turns into 503 MODEL_NOT_LOADED."""
    predictor = get_predictor(name)
    with pytest.raises(ModelNotLoadedError) as excinfo:
        predictor.predict(features=[[0.0, 0.0, 1.0]] * 400)

    assert name in str(excinfo.value)
    assert excinfo.value.model_name == name


# ---------------------------------------------------------------------------
# Fall detection
# ---------------------------------------------------------------------------


def test_fall_detection_returns_the_real_predictor() -> None:
    """Fall detection is the one capability with an implementation behind it."""
    predictor = get_predictor("fall_detection")
    assert isinstance(predictor, FallDetectionPredictor)


def test_fall_detection_without_a_model_file_is_not_ready() -> None:
    """The model file is git-ignored, so a fresh clone has none.

    The assertions below describe the fresh-clone state. If a model has been
    trained locally the test skips instead of failing, because the trained
    artefact is not part of the repository.
    """
    if _fall_model_path().exists():
        pytest.skip(
            "A trained fall-detection model is present locally, so the "
            "no-model state cannot be observed from this checkout."
        )

    predictor = get_predictor("fall_detection")
    assert predictor.is_ready() is False
    assert predictor.info.metrics is None
    assert predictor.info.version == ""


# ---------------------------------------------------------------------------
# list_predictors
# ---------------------------------------------------------------------------


def test_list_predictors_covers_every_declared_capability() -> None:
    described = list_predictors()
    assert [entry["name"] for entry in described] == list(AVAILABLE_PREDICTORS)


def test_every_listed_predictor_has_the_documented_keys() -> None:
    """The API serialises these entries directly, so the shape is a contract."""
    expected_keys = {
        "name",
        "is_ready",
        "model_version",
        "trained_at",
        "metrics",
        "dataset",
    }
    for entry in list_predictors():
        assert set(entry) == expected_keys


def test_listed_predictors_never_invent_metrics() -> None:
    """A capability with no model reports `metrics: None`, not zeros."""
    for entry in list_predictors():
        if not entry["is_ready"]:
            assert entry["metrics"] is None


def test_listed_predictors_name_their_planned_dataset() -> None:
    """Provenance is reported even for the capabilities that have no model."""
    datasets = {entry["name"]: entry["dataset"] for entry in list_predictors()}
    assert datasets["fall_detection"] == "SisFall"
    assert datasets["activity_recognition"] == "UCI HAR"
    assert datasets["anomaly_detection"] == "CASAS"
