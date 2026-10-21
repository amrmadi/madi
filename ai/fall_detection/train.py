"""Train the SisFall fall-detection baseline and write the serving artefacts.

Run it with:

    python -m ai.fall_detection.train --help

What it does, in order
----------------------
1. **Inventories the archive.** The subject list is read from the dataset
   itself (`all_subjects`, `elderly_subjects`, `subjects_with_falls`) rather
   than hard-coded, so the split cannot drift away from the data that is
   actually there.
2. **Splits by subject** (`split_subjects`). People, not rows, are divided
   between train and test. This is the single most important correctness
   property of the whole pipeline: SisFall records each volunteer for many
   seconds at 200 Hz, so a row-wise split would put windows from the same
   person on both sides and turn the evaluation into a measurement of
   memorisation. The two subject lists are printed in full so the split can
   be checked by eye.
3. **Windows the recordings** (`build_windows`, 2 s windows, 50 % overlap).
   Every window is 400 rows long whichever recording it came from, so a fall
   and a long stretch of ordinary activity are not separated by their length.
4. **Fits the scaler on the training windows only** (`fit_scaler`). Fitting it
   on everything would let the test set's own mean and variance leak into the
   model, and the score would be quietly optimistic.
5. **Trains a `RandomForestClassifier`** on the scaled training matrix and
   evaluates it on the held-out **subjects**.
6. **Reports measured numbers** — precision, recall and F1 for the fall class,
   the accuracy, a sweep over operating thresholds, and a separate evaluation
   of the elderly subset.
7. **Writes two artefacts**: `<model-version>.joblib` (the estimator and its
   metadata) and `<model-version>.json` (the same metadata, readable without
   unpickling). Both go into `ai/models/fall_detection/`, which is
   git-ignored: the dataset and the trained model are never committed.

Honesty rules this script follows
---------------------------------
* If the dataset is not on disk it says so and exits non-zero. It does not
  substitute synthetic data for the real archive, and it does not write a
  model that was never trained.
* If scikit-learn is missing it says so and exits non-zero, pointing at the
  install command. The module itself still imports and `--help` still works
  without scikit-learn, because the import happens inside `train()`.
* Metrics printed here are **measured on the held-out subjects of this run**.
  They are not carried over from an earlier run and they are never invented.
* The elderly evaluation is reported separately and always with the caveat
  that SisFall contains only one elderly volunteer who simulated falls, so an
  "elderly" number here describes one person, not a population.

Dependencies
------------
`numpy` is needed to import this module; `scikit-learn` and `joblib` are
needed only to actually train, and are imported inside `train()` so that
`--help` works in an environment where they are absent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

from ai.fall_detection import preprocess as pp

__all__ = ["build_parser", "main", "train"]

#: Repository root, used to resolve relative paths consistently. `train.py`
#: lives at `<root>/ai/fall_detection/train.py`.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Where the unzipped SisFall archive is expected to live.
DEFAULT_ARCHIVE = "data/raw/SisFall_dataset.zip"

#: Where the trained artefacts are written. The predictor looks in the same
#: place by default (`ai/fall_detection/predictor.py: DEFAULT_MODEL_DIR`).
DEFAULT_OUTPUT_DIR = "ai/models/fall_detection"

#: Share of **subjects** held back for testing.
DEFAULT_TEST_FRACTION = 0.25

#: Seed for the subject shuffle and the forest. Fixed so a rerun reproduces
#: the same split and the same numbers.
DEFAULT_SEED = 20260101

#: Identifier stored in the artefacts and reported by the API.
DEFAULT_MODEL_VERSION = "fall-rf-v1"

#: Probability at or above which a window is called a fall.
DEFAULT_THRESHOLD = 0.5

#: The baseline classifier. `balanced_subsample` matters because SisFall is
#: heavily imbalanced: there are far more windows of ordinary activity than
#: windows containing a fall, and an unweighted forest would simply learn to
#: say "no fall" and score well on accuracy alone.
RANDOM_FOREST_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "class_weight": "balanced_subsample",
    "n_jobs": -1,
}

#: Thresholds reported in the printed sweep. The operating threshold itself
#: is always included, whatever it is.
SWEEP_THRESHOLDS: tuple[float, ...] = (0.3, 0.4, 0.5, 0.6, 0.7)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TrainingError(RuntimeError):
    """Base class for the failures this script reports and exits on."""


class MissingDatasetError(TrainingError):
    """The SisFall archive is not where the user said it would be."""


class MissingDependencyError(TrainingError):
    """scikit-learn or joblib is not installed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_path(value: str) -> pathlib.Path:
    """Resolve a command-line path.

    Relative paths are resolved against the **repository root** rather than
    the current working directory, so the command behaves identically whether
    it is started from the root or from a subdirectory. Absolute paths are
    used exactly as given.
    """
    candidate = pathlib.Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def _binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Precision, recall and F1 for the positive (fall) class.

    Written out by hand rather than imported from `sklearn.metrics` so the
    definition is unambiguous and does not depend on a library version:
    precision is the share of predicted falls that were really falls, recall
    is the share of real falls that were found.

    An empty denominator yields 0.0. That case is never silent — the caller
    checks whether the evaluation split contains any fall windows at all and
    refuses to report a score it cannot measure.
    """
    true_positive = float(np.sum((y_true == 1) & (y_pred == 1)))
    false_positive = float(np.sum((y_true == 0) & (y_pred == 1)))
    false_negative = float(np.sum((y_true == 1) & (y_pred == 0)))

    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative

    precision = true_positive / predicted_positive if predicted_positive else 0.0
    recall = true_positive / actual_positive if actual_positive else 0.0
    denominator = precision + recall
    f1 = (2.0 * precision * recall / denominator) if denominator else 0.0
    total = float(np.size(y_true))
    accuracy = float(np.sum(y_true == y_pred)) / total if total else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "true_positives": true_positive,
        "false_positives": false_positive,
        "false_negatives": false_negative,
    }


def _windows_for(recordings: Iterable[pp.Recording]) -> list[pp.Window]:
    """Cut every recording into overlapping, feature-extracted windows."""
    windows: list[pp.Window] = []
    for recording in recordings:
        windows.extend(
            pp.build_windows(
                recording,
                window_rows=pp.DEFAULT_WINDOW_ROWS,
                stride=pp.DEFAULT_STRIDE,
            )
        )
    return windows


def _labels_for(windows: Sequence[pp.Window]) -> np.ndarray:
    """The fall/no-fall label of every window, as an integer array."""
    return np.asarray([w.label for w in windows], dtype=np.int64)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train(args: argparse.Namespace) -> dict[str, Any]:
    """Train the model and write the artefacts.

    Returns the artefact dictionary that was written to disk, so a caller (or
    a test) can inspect exactly what the predictor will load.
    """
    archive = _resolve_path(args.archive)
    output_dir = _resolve_path(args.output_dir)

    # -- the dataset must actually be there ---------------------------------
    if not archive.is_file():
        raise MissingDatasetError(
            f"the SisFall archive was not found at\n"
            f"    {archive}\n"
            f"\n"
            f"The dataset is not committed to this repository (it is roughly "
            f"220 MB and git-ignored).\n"
            f"Download it from the source, size and checksum recorded in\n"
            f"    docs/datasets/sisfall.md\n"
            f"and place the zip file at the path above, then run this command "
            f"again:\n"
            f"    python -m ai.fall_detection.train "
            f"--archive {args.archive}\n"
            f"\n"
            f"Nothing was trained and no model file was written."
        )

    # -- the learning dependencies must be installed ------------------------
    try:
        import joblib
        from sklearn.ensemble import RandomForestClassifier
    except ImportError as exc:
        raise MissingDependencyError(
            f"scikit-learn and joblib are required to train the model, but "
            f"importing them failed ({exc}).\n"
            f"Install them with:\n"
            f"    python -m pip install scikit-learn joblib\n"
            f"Nothing was trained and no model file was written."
        ) from exc

    print("SisFall fall-detection training")
    print("=" * 72)
    print(f"archive        : {archive}")
    print(f"output dir     : {output_dir}")
    print(f"model version  : {args.model_version}")
    print(f"test fraction  : {args.test_fraction} (of subjects, not windows)")
    print(f"seed           : {args.seed}")
    print(f"threshold      : {args.threshold}")
    print()

    # -- inventory ----------------------------------------------------------
    subjects = pp.all_subjects(archive)
    elderly = pp.elderly_subjects(archive)
    fall_subjects = pp.subjects_with_falls(archive)
    elderly_fall_subjects = sorted(s for s in elderly if s in fall_subjects)

    print(f"subjects in archive        : {len(subjects)}")
    print(f"  adult                    : {len(subjects) - len(elderly)}")
    print(f"  elderly                  : {len(elderly)}")
    print(f"subjects with >=1 fall     : {len(fall_subjects)}")
    print(
        f"  of which elderly         : {len(elderly_fall_subjects)} "
        f"({', '.join(elderly_fall_subjects) or 'none'})"
    )
    print()

    # -- the split ----------------------------------------------------------
    train_subjects, test_subjects = pp.split_subjects(
        subjects,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    # Guard the invariant explicitly rather than trusting the helper.
    if set(train_subjects) & set(test_subjects):
        raise TrainingError(
            "Internal error: the train and test subject lists overlap, which "
            "would invalidate the evaluation."
        )
    elderly_test_subjects = [s for s in test_subjects if s in elderly]

    print("subject-wise split (never row-wise)")
    print(f"  train subjects ({len(train_subjects)}): {', '.join(train_subjects)}")
    print(f"  test  subjects ({len(test_subjects)}): {', '.join(test_subjects)}")
    print(f"  elderly test subjects: {', '.join(elderly_test_subjects) or 'none'}")
    print()

    # -- windowing ----------------------------------------------------------
    print("building windows...")
    train_windows = _windows_for(
        pp.iter_archive_recordings(archive, subjects=train_subjects)
    )
    test_windows = _windows_for(
        pp.iter_archive_recordings(archive, subjects=test_subjects)
    )
    print(f"  train windows : {len(train_windows)}")
    print(f"  test windows  : {len(test_windows)}")
    print(
        f"  window = {pp.DEFAULT_WINDOW_ROWS} rows "
        f"({pp.DEFAULT_WINDOW_ROWS / pp.SAMPLE_RATE_HZ:.1f} s at "
        f"{pp.SAMPLE_RATE_HZ} Hz), stride = {pp.DEFAULT_STRIDE} rows"
    )
    print()

    if not train_windows:
        raise TrainingError(
            "The training split produced no windows. Check that the archive "
            "is the real SisFall dataset and that the window length is not "
            "longer than the recordings."
        )
    if not test_windows:
        raise TrainingError(
            "The held-out split produced no windows, so the model could not "
            "be evaluated. Try a different --seed or a larger "
            "--test-fraction."
        )

    y_train = _labels_for(train_windows)
    y_test = _labels_for(test_windows)

    if int(np.sum(y_train == 1)) == 0:
        raise TrainingError(
            "The training split contains no fall windows, so there is "
            "nothing to learn a fall from. Try a different --seed or a "
            "larger --test-fraction so that fall recordings land on both "
            "sides of the split."
        )
    if int(np.sum(y_train == 0)) == 0:
        raise TrainingError(
            "The training split contains no ordinary-activity (no-fall) "
            "windows, so there is nothing to distinguish a fall from. Both "
            "classes must be present for a two-class model to be trained."
        )
    if int(np.sum(y_test == 1)) == 0:
        raise TrainingError(
            "The held-out split contains no fall windows, so precision, "
            "recall and F1 for the fall class cannot be measured. Reporting "
            "a number here would be inventing one. Try a different --seed or "
            "a larger --test-fraction."
        )

    # -- scaling (train windows only) ---------------------------------------
    scaler = pp.fit_scaler([w.features for w in train_windows])
    scale_values = np.asarray(scaler.scale, dtype=np.float64)
    if not np.all(scale_values > 0.0):
        raise TrainingError(
            "The fitted scaler contains a non-positive scale value, which "
            "would divide by zero at serving time. This should be "
            "impossible — `fit_scaler` replaces zero-variance features with "
            "1.0 — so the preprocessing module needs a look."
        )

    x_train = scaler.transform(pp.feature_matrix(train_windows))
    x_test = scaler.transform(pp.feature_matrix(test_windows))

    # -- fit ----------------------------------------------------------------
    print("fitting the random forest...")
    model = RandomForestClassifier(random_state=args.seed, **RANDOM_FOREST_PARAMS)
    model.fit(x_train, y_train)
    probabilities = np.asarray(model.predict_proba(x_test)[:, 1], dtype=np.float64)

    # -- evaluate -----------------------------------------------------------
    predicted = (probabilities >= args.threshold).astype(np.int64)
    overall = _binary_metrics(y_test, predicted)

    metrics: dict[str, float] = {
        "precision_fall": overall["precision"],
        "recall_fall": overall["recall"],
        "f1_fall": overall["f1"],
        "accuracy": overall["accuracy"],
        "support_fall": float(np.sum(y_test == 1)),
        "support_adl": float(np.sum(y_test == 0)),
        "n_train_windows": float(len(train_windows)),
        "n_test_windows": float(len(test_windows)),
        "n_train_subjects": float(len(train_subjects)),
        "n_test_subjects": float(len(test_subjects)),
    }

    print("measured on the held-out subjects")
    print(f"  threshold        : {args.threshold}")
    print(f"  precision (fall) : {overall['precision']:.3f}")
    print(f"  recall    (fall) : {overall['recall']:.3f}")
    print(f"  F1        (fall) : {overall['f1']:.3f}")
    print(f"  accuracy         : {overall['accuracy']:.3f}")
    print(
        f"  test windows     : {int(np.sum(y_test == 1))} fall / "
        f"{int(np.sum(y_test == 0))} no-fall"
    )
    print()

    # The elderly subset is reported separately, and only if it can be
    # measured at all.
    elderly_windows = [w for w in test_windows if w.cohort == "elderly"]
    elderly_has_falls = any(w.label == 1 for w in elderly_windows)
    if elderly_windows and elderly_has_falls:
        elderly_y = _labels_for(elderly_windows)
        elderly_probabilities = np.asarray(
            model.predict_proba(
                scaler.transform(pp.feature_matrix(elderly_windows))
            )[:, 1],
            dtype=np.float64,
        )
        elderly_predicted = (elderly_probabilities >= args.threshold).astype(np.int64)
        elderly_metrics = _binary_metrics(elderly_y, elderly_predicted)
        metrics.update(
            {
                "elderly_precision_fall": elderly_metrics["precision"],
                "elderly_recall_fall": elderly_metrics["recall"],
                "elderly_f1_fall": elderly_metrics["f1"],
                "elderly_accuracy": elderly_metrics["accuracy"],
                "elderly_support_fall": float(np.sum(elderly_y == 1)),
                "elderly_n_test_windows": float(len(elderly_windows)),
                "elderly_n_test_subjects": float(len(elderly_test_subjects)),
            }
        )
        print("elderly subset of the held-out subjects")
        print(f"  subjects         : {', '.join(elderly_test_subjects) or 'none'}")
        print(f"  windows          : {len(elderly_windows)}")
        print(f"  precision (fall) : {elderly_metrics['precision']:.3f}")
        print(f"  recall    (fall) : {elderly_metrics['recall']:.3f}")
        print(f"  F1        (fall) : {elderly_metrics['f1']:.3f}")
        print(
            "  CAVEAT: SisFall contains only one elderly volunteer who "
            "simulated falls, so this\n  number describes that one person's "
            "recordings. It is not an estimate\n  of performance on elderly "
            "people in general."
        )
        print()
    else:
        print("elderly subset of the held-out subjects")
        if not elderly_windows:
            print(
                "  no elderly subject landed in the test split, so there is "
                "nothing to evaluate."
            )
        else:
            print(
                "  the elderly subjects in the test split produced no fall "
                "windows, so precision,\n  recall and F1 cannot be measured "
                "for this subset and are omitted\n  rather than reported as "
                "zero."
            )
        print()

    # -- threshold sweep ----------------------------------------------------
    print("threshold sweep on the held-out subjects")
    print("  threshold  precision  recall  F1")
    for sweep_threshold in sorted(set(SWEEP_THRESHOLDS) | {float(args.threshold)}):
        sweep_predicted = (probabilities >= sweep_threshold).astype(np.int64)
        sweep = _binary_metrics(y_test, sweep_predicted)
        print(
            f"  {sweep_threshold:9.2f}  {sweep['precision']:9.3f}  "
            f"{sweep['recall']:6.3f}  {sweep['f1']:5.3f}"
        )
    print()

    # -- artefacts ----------------------------------------------------------
    command = "python -m ai.fall_detection.train"
    if sys.argv[1:]:
        command = f"{command} {' '.join(sys.argv[1:])}"

    metadata: dict[str, Any] = {
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "metrics": metrics,
        "train_subjects": list(train_subjects),
        "test_subjects": list(test_subjects),
        "elderly_test_subjects": list(elderly_test_subjects),
        "command": command,
    }

    artefacts: dict[str, Any] = {
        "model": model,
        "scaler": scaler.as_dict(),
        "feature_names": pp.feature_names(),
        "threshold": float(args.threshold),
        "window_rows": int(pp.DEFAULT_WINDOW_ROWS),
        "sample_rate_hz": int(pp.SAMPLE_RATE_HZ),
        "model_version": str(args.model_version),
        "dataset": "SisFall",
        "metrics": metrics,
        "metadata": metadata,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    joblib_path = output_dir / f"{args.model_version}.joblib"
    json_path = output_dir / f"{args.model_version}.json"

    joblib.dump(artefacts, joblib_path)

    # The JSON twin exists so the metadata can be read without unpickling the
    # estimator — for a log, a report, or a reviewer without joblib.
    json_payload: dict[str, Any] = dict(metadata)
    json_payload.update(
        {
            "model_version": str(args.model_version),
            "dataset": "SisFall",
            "threshold": float(args.threshold),
            "window_rows": int(pp.DEFAULT_WINDOW_ROWS),
            "sample_rate_hz": int(pp.SAMPLE_RATE_HZ),
            "feature_names": pp.feature_names(),
            "model_file": joblib_path.name,
        }
    )
    json_path.write_text(
        json.dumps(json_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("artefacts written")
    print(f"  {joblib_path}")
    print(f"  {json_path}")
    print(
        "  The default output directory (ai/models/) is git-ignored "
        "(.gitignore lists ai/**/models/\n  and *.joblib), so a trained "
        "model is never committed: a fresh clone reports fall\n  detection "
        "as unavailable until it is retrained."
    )
    print()
    print("done.")
    return artefacts


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Kept separate from `main()` so `--help` can be exercised without running
    anything, and so the options are documented in one place.
    """
    parser = argparse.ArgumentParser(
        prog="python -m ai.fall_detection.train",
        description=(
            "Train the SisFall fall-detection baseline and write the "
            "artefacts the predictor loads. The dataset is not committed to "
            "this repository; see docs/datasets/sisfall.md for where to get "
            "it."
        ),
        epilog=(
            "Relative paths are resolved against the repository root. "
            "Example:\n"
            "  python -m ai.fall_detection.train "
            "--archive data/raw/SisFall_dataset.zip --output-dir "
            "ai/models/fall_detection"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--archive",
        default=DEFAULT_ARCHIVE,
        help=(
            "Path to the SisFall_dataset.zip archive. "
            f"(default: {DEFAULT_ARCHIVE})"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Directory the trained artefacts are written to. "
            f"(default: {DEFAULT_OUTPUT_DIR})"
        ),
    )
    parser.add_argument(
        "--test-fraction",
        type=float,
        default=DEFAULT_TEST_FRACTION,
        help=(
            "Share of SUBJECTS held back for testing, not a share of rows. "
            f"(default: {DEFAULT_TEST_FRACTION})"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=(
            "Seed for the subject split and the forest, so a rerun reproduces "
            f"the same result. (default: {DEFAULT_SEED})"
        ),
    )
    parser.add_argument(
        "--model-version",
        default=DEFAULT_MODEL_VERSION,
        help=(
            "Identifier written into the artefacts and reported by the API. "
            f"(default: {DEFAULT_MODEL_VERSION})"
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=(
            "Probability at or above which a window is called a fall. "
            f"(default: {DEFAULT_THRESHOLD})"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        train(args)
    except TrainingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
