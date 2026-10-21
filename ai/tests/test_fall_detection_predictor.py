"""Tests for `ai/fall_detection/predictor.py` — the serving side.

What matters here
-----------------
The predictor's job when there is no model is to say so, loudly and
specifically, rather than to return a plausible-looking answer. That is the
behaviour the API turns into an honest `503 MODEL_NOT_LOADED`, so it is
tested directly.

These tests are **hermetic**: they point the predictor at an empty
directory (`tmp_path`), so they never depend on a trained model file being
present. The trained model is git-ignored, so a fresh clone does not have one
and a developer's machine might — the tests must give the same answer in
both cases.

The assertions that need a real model are skipped when there is none, rather
than faked: building a stand-in estimator would need scikit-learn, and this
suite is required to run with numpy alone.
"""

from __future__ import annotations

import pytest

from ai.base import ModelNotLoadedError
from ai.fall_detection.predictor import FallDetectionPredictor


#: 400 samples is one 2 s window at 200 Hz.
ONE_WINDOW = [[0.0, 0.0, 0.0]] * 400


# ---------------------------------------------------------------------------
# With no model file
# ---------------------------------------------------------------------------


def test_a_predictor_without_a_model_is_not_ready(tmp_path) -> None:
    """`tmp_path` is an empty directory, so there is certainly no model."""
    predictor = FallDetectionPredictor(model_dir=tmp_path)
    assert predictor.is_ready() is False


def test_a_predictor_without_a_model_refuses_to_predict(tmp_path) -> None:
    """This is the honest alternative to inventing a fall prediction."""
    predictor = FallDetectionPredictor(model_dir=tmp_path)

    with pytest.raises(ModelNotLoadedError) as excinfo:
        predictor.predict(ONE_WINDOW)

    assert "fall_detection" in str(excinfo.value)
    assert excinfo.value.model_name == "fall_detection"
    assert excinfo.value.reason


def test_a_predictor_without_a_model_reports_no_metrics(tmp_path) -> None:
    """No model means no measured metrics. Zeros would be a fabrication."""
    predictor = FallDetectionPredictor(model_dir=tmp_path)
    info = predictor.info

    assert info.metrics is None
    assert info.version == ""
    assert info.trained_at is None
    assert info.name == "fall_detection"
    assert info.kind == "fall_detection"
    assert info.dataset == "SisFall"


def test_a_predictor_without_a_model_reports_no_version(tmp_path) -> None:
    """`info.version` is empty, not the default model name: nothing is loaded."""
    predictor = FallDetectionPredictor(model_dir=tmp_path)
    assert predictor.info.version == ""


# ---------------------------------------------------------------------------
# With a model file (skipped when there is none)
# ---------------------------------------------------------------------------


def _trained_predictor() -> FallDetectionPredictor:
    """A predictor on the real artefacts, or a skip when they are absent.

    The trained model is git-ignored, so this returns the default predictor
    only on a machine where the model has been trained. Everywhere else the
    test skips — it never stands a fake model in, because building one would
    need scikit-learn and this suite has to run with numpy alone.
    """
    predictor = FallDetectionPredictor()
    if not predictor.is_ready():
        pytest.skip(
            "No trained model file is present, so this path cannot be "
            "reached. Train one with 'python -m ai.fall_detection.train'."
        )
    return predictor


def test_predict_rejects_a_badly_shaped_input() -> None:
    """Samples must be an (n, 3) array in grams."""
    predictor = _trained_predictor()

    with pytest.raises(ValueError):
        predictor.predict([[0.0, 0.0]] * 400)


def test_predict_rejects_a_sequence_shorter_than_one_window() -> None:
    """Half a window is not a measurement; the predictor says so."""
    predictor = _trained_predictor()

    with pytest.raises(ValueError):
        predictor.predict([[0.0, 0.0, 1.0]] * 10)


def test_a_loaded_predictor_reports_its_version_and_metrics() -> None:
    predictor = _trained_predictor()
    info = predictor.info

    assert info.version
    assert info.metrics is not None
    assert info.trained_at is not None


def test_a_loaded_predictor_flags_its_result_as_simulated() -> None:
    """SisFall is other people's data, so it is never a resident's reading."""
    predictor = _trained_predictor()

    result = predictor.predict(ONE_WINDOW)
    assert result.source == "imported_dataset"
    assert result.is_simulated is True
    assert result.needs_human_review is result.is_fall
