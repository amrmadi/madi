"""Tests for `ai/fall_detection/preprocess.py` — the rules that must not drift.

What is worth testing here
---------------------------
The preprocessing module exists so that the *rules* of a fall detector live
in one place: the unit conversion, the parser's tolerance of malformed rows,
the subject parsing, the subject-wise split, the window count and the
train-only scaler. Each of those is a place where a small mistake produces a
number that looks fine and is meaningless — for example a scaler fitted on
the test set, or a split that leaks a person across both sides.

Every test here runs on synthetic data: **no dataset, no network, no
scikit-learn, and no trained model are needed.**
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ai.fall_detection import preprocess as pp


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------


def test_one_adc_count_is_thirty_two_over_eight_thousand_one_hundred_and_ninety_two() -> None:
    """The dataset Readme's formula: (2 * Range) / 2**Resolution g per count.

    With Range = 16 g and Resolution = 13 bits that is 32 / 8192 g, so
    256 counts is exactly 1 g.
    """
    assert pp.ADXL345_G_PER_ADC_BIT == 32.0 / 8192.0
    assert math.isclose(pp.ADXL345_G_PER_ADC_BIT, 0.00390625)

    converted = pp.counts_to_g(np.array([0.0, 1.0, 256.0, -256.0]))
    assert converted[0] == 0.0
    assert converted[1] == pytest.approx(32.0 / 8192.0)
    assert converted[2] == pytest.approx(1.0)
    assert converted[3] == pytest.approx(-1.0)


def test_the_conversion_matches_the_readme_formula_for_a_range_of_counts() -> None:
    counts = np.array([-4096.0, -256.0, 0.0, 100.0, 4095.0])
    expected = (2.0 * 16.0) / (2.0**13) * counts
    assert np.allclose(pp.counts_to_g(counts), expected)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

#: A synthetic recording in the shape the real files have: nine space-padded
#: integer fields per row, terminated with `;`. The last two rows are
#: deliberately broken and must be skipped.
SAMPLE_RECORDING = (
    "  256,    0,  -256,    0,    0,    0,    0,    0,    0;\r\n"
    "  256,    0,  -256,    0,    0,    0,    0,    0,    0;\r\n"
    "this line is not a row at all\r\n"
    "  1,    2,    3;\r\n"  # too few fields
    "  1.5,    2,    3,    4,    5,    6,    7,    8,    9;\r\n"  # not integers
    "  512,    0,  -512,    0,    0,    0,    0,    0,    0;\r\n"
)


def test_parse_recording_returns_one_row_per_valid_sample() -> None:
    parsed = pp.parse_recording(SAMPLE_RECORDING)
    assert parsed.shape == (3, 3)


def test_parse_recording_converts_to_grams() -> None:
    parsed = pp.parse_recording(SAMPLE_RECORDING)
    assert parsed[0][0] == pytest.approx(1.0)
    assert parsed[0][1] == pytest.approx(0.0)
    assert parsed[0][2] == pytest.approx(-1.0)
    assert parsed[2][0] == pytest.approx(2.0)
    assert parsed[2][2] == pytest.approx(-2.0)


def test_parse_recording_skips_malformed_rows() -> None:
    """A mis-parsed row would become a fake acceleration spike."""
    parsed = pp.parse_recording(SAMPLE_RECORDING)
    # A spike of 256 g would mean the bad rows had been coerced rather than
    # skipped; the largest magnitude must stay near the values we wrote.
    assert float(np.max(np.abs(parsed))) == pytest.approx(2.0)


def test_parse_recording_handles_a_missing_trailing_semicolon() -> None:
    """The `;` terminates a row; it is not required to be there."""
    without_semicolon = "  256,    0,  -256,    0,    0,    0,    0,    0,    0\r\n"
    parsed = pp.parse_recording(without_semicolon)
    assert parsed.shape == (1, 3)
    assert parsed[0][0] == pytest.approx(1.0)


def test_parse_recording_of_an_empty_file_is_an_empty_array() -> None:
    parsed = pp.parse_recording("")
    assert parsed.shape == (0, 3)


# ---------------------------------------------------------------------------
# Subject codes
# ---------------------------------------------------------------------------


def test_subject_of_an_adult_fall_file() -> None:
    assert pp.subject_of("F01_SA01_R01.txt") == ("SA01", "adult")


def test_subject_of_an_elderly_file() -> None:
    assert pp.subject_of("D02_SE06_R03.txt") == ("SE06", "elderly")


def test_subject_of_a_bad_name_raises() -> None:
    """A mis-named file must be caught, not silently assigned the wrong
    subject — that would corrupt the subject-wise split."""
    for bad_name in ("notes.txt", "F01_SX01_R01.txt", "F01_SA01.txt", ""):
        with pytest.raises(ValueError):
            pp.subject_of(bad_name)


# ---------------------------------------------------------------------------
# The subject-wise split
# ---------------------------------------------------------------------------


def test_the_split_divides_the_subjects_without_overlap() -> None:
    subjects = [f"SA{n:02d}" for n in range(1, 11)]
    train, test = pp.split_subjects(subjects, test_fraction=0.25, seed=20260101)

    assert set(train).isdisjoint(test)
    assert sorted(train + test) == sorted(subjects)


def test_the_split_keeps_every_subject_exactly_once() -> None:
    subjects = [f"SA{n:02d}" for n in range(1, 11)] + ["SE01", "SE02"]
    train, test = pp.split_subjects(subjects, test_fraction=0.25, seed=20260101)

    assert len(train) + len(test) == len(subjects)
    assert len(set(train)) == len(train)
    assert len(set(test)) == len(test)


def test_the_split_is_deterministic_for_a_fixed_seed() -> None:
    subjects = [f"SA{n:02d}" for n in range(1, 11)] + ["SE01", "SE02"]
    first = pp.split_subjects(subjects, test_fraction=0.25, seed=20260101)
    second = pp.split_subjects(subjects, test_fraction=0.25, seed=20260101)
    assert first == second


def test_the_split_changes_with_the_seed() -> None:
    """A different seed must be able to produce a different split, otherwise
    the seed would not be doing anything."""
    subjects = [f"SA{n:02d}" for n in range(1, 21)]
    first = pp.split_subjects(subjects, test_fraction=0.25, seed=1)
    second = pp.split_subjects(subjects, test_fraction=0.25, seed=2)
    assert first != second


def test_the_split_rejects_an_empty_subject_list() -> None:
    with pytest.raises(ValueError):
        pp.split_subjects([], test_fraction=0.25, seed=1)


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.5, 1.5])
def test_the_split_rejects_an_out_of_range_test_fraction(fraction: float) -> None:
    with pytest.raises(ValueError):
        pp.split_subjects(["SA01", "SA02"], test_fraction=fraction, seed=1)


def test_the_split_never_hands_the_test_set_everything() -> None:
    """Even a large test fraction must leave something to train on."""
    subjects = ["SA01", "SA02", "SA03"]
    train, test = pp.split_subjects(subjects, test_fraction=0.99, seed=1)
    assert train
    assert test
    assert set(train).isdisjoint(test)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


def test_extract_features_returns_exactly_the_declared_feature_names() -> None:
    samples = np.random.default_rng(0).normal(size=(400, 3))
    features = pp.extract_features(samples)

    assert list(features) == pp.feature_names()
    assert len(features) == 40
    assert len(pp.feature_names()) == 40


def test_feature_names_cover_the_four_signals_and_ten_statistics() -> None:
    names = pp.feature_names()
    for axis in ("x", "y", "z", "mag"):
        for suffix in (
            "mean",
            "std",
            "min",
            "max",
            "median",
            "iqr",
            "rms",
            "range",
            "mean_abs_diff",
            "zero_crossings",
        ):
            assert f"{axis}_{suffix}" in names


@pytest.mark.parametrize(
    "bad_shape", [(10, 2), (10, 4), (10,), (10, 3, 2)]
)
def test_extract_features_rejects_an_array_that_is_not_n_by_three(bad_shape: tuple) -> None:
    with pytest.raises(ValueError):
        pp.extract_features(np.zeros(bad_shape))


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------


def _recording(n_samples: int, label: int = 0) -> pp.Recording:
    """A synthetic recording of the given length, in grams."""
    rng = np.random.default_rng(1)
    return pp.Recording(
        code="F01" if label else "D01",
        subject="SA01",
        cohort="adult",
        run="01",
        label=label,
        accel_g=rng.normal(size=(n_samples, 3)),
    )


def test_build_windows_produces_the_expected_number_of_windows() -> None:
    """1000 rows, 400-row windows, stride 200 -> starts at 0, 200, 400, 600."""
    windows = pp.build_windows(_recording(1000), window_rows=400, stride=200)
    assert len(windows) == 4
    assert [w.start_row for w in windows] == [0, 200, 400, 600]


def test_build_windows_drops_a_trailing_remainder() -> None:
    """A 0.2 s fragment is not a fall candidate."""
    windows = pp.build_windows(_recording(1050), window_rows=400, stride=200)
    assert [w.start_row for w in windows] == [0, 200, 400, 600]


def test_build_windows_of_a_short_recording_is_empty() -> None:
    assert pp.build_windows(_recording(399), window_rows=400, stride=200) == []


def test_build_windows_rejects_a_stride_longer_than_the_window() -> None:
    with pytest.raises(ValueError):
        pp.build_windows(_recording(1000), window_rows=400, stride=500)


def test_build_windows_keeps_the_recording_label() -> None:
    windows = pp.build_windows(_recording(1000, label=1), window_rows=400, stride=200)
    assert all(w.label == 1 for w in windows)


# ---------------------------------------------------------------------------
# The train-only scaler
# ---------------------------------------------------------------------------


def test_fit_scaler_rejects_an_empty_training_set() -> None:
    with pytest.raises(ValueError):
        pp.fit_scaler([])


def test_a_constant_feature_gets_a_scale_of_one() -> None:
    """A zero-variance feature must not divide by zero at serving time."""
    constant = np.ones((400, 3))
    rows = [pp.extract_features(constant), pp.extract_features(constant)]

    scaler = pp.fit_scaler(rows)
    scale = np.asarray(scaler.scale, dtype=np.float64)

    assert np.all(scale == 1.0)
    assert not np.any(scale == 0.0)


def test_the_scaler_never_produces_a_zero_scale() -> None:
    rng = np.random.default_rng(3)
    rows = [pp.extract_features(rng.normal(size=(400, 3))) for _ in range(5)]
    scaler = pp.fit_scaler(rows)
    assert not np.any(np.asarray(scaler.scale) == 0.0)


def test_the_scaler_records_the_feature_names_in_order() -> None:
    rng = np.random.default_rng(4)
    rows = [pp.extract_features(rng.normal(size=(400, 3))) for _ in range(3)]
    scaler = pp.fit_scaler(rows)
    assert list(scaler.names) == pp.feature_names()


def test_the_scaler_dictionary_has_the_shape_the_predictor_expects() -> None:
    """`predictor.py` reads `scaler_meta["mean"]` and `scaler_meta["scale"]`."""
    rng = np.random.default_rng(5)
    rows = [pp.extract_features(rng.normal(size=(400, 3))) for _ in range(3)]
    scaler_dict = pp.fit_scaler(rows).as_dict()

    assert set(scaler_dict) == {"names", "mean", "scale"}
    assert len(scaler_dict["mean"]) == len(pp.feature_names())
    assert len(scaler_dict["scale"]) == len(pp.feature_names())
    assert all(isinstance(value, float) for value in scaler_dict["mean"])


# ---------------------------------------------------------------------------
# The feature matrix
# ---------------------------------------------------------------------------


def test_feature_matrix_builds_one_row_per_window() -> None:
    windows = pp.build_windows(_recording(1000), window_rows=400, stride=200)
    matrix = pp.feature_matrix(windows)
    assert matrix.shape == (4, 40)


def test_feature_matrix_names_the_missing_feature() -> None:
    """A missing feature must be a clear ValueError, not a bare KeyError."""
    features = pp.extract_features(np.ones((400, 3)))
    del features["x_std"]

    window = pp.Window(
        subject="SA01",
        cohort="adult",
        code="D01",
        run="01",
        label=0,
        start_row=0,
        features=features,
    )

    with pytest.raises(ValueError) as excinfo:
        pp.feature_matrix([window])

    assert "x_std" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The dataset constants
# ---------------------------------------------------------------------------


def test_the_dataset_constants_match_the_dataset() -> None:
    assert pp.SAMPLE_RATE_HZ == 200
    assert pp.DEFAULT_WINDOW_ROWS == 400
    assert pp.DEFAULT_STRIDE == 200
    assert pp.ADXL345_RANGE_G == 16.0
    assert pp.ADXL345_RESOLUTION_BITS == 13
