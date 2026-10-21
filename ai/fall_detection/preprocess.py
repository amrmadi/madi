"""SisFall preprocessing: raw sensor files -> labelled feature windows.

Why this module exists
----------------------
`ai/fall_detection/` needs a single, testable place that turns the raw SisFall
text files into the numeric table a model can be trained on. Without it, the
conversion rules and — more importantly — the **subject-wise split** would be
re-implemented slightly differently in every script, and a mistake there is
silent: it does not crash, it just produces a number that flatters the model.

The three mistakes this module is written to make impossible
-----------------------------------------------------------
1. **Row-wise splitting.** SisFall records each person for many seconds at
   ~200 Hz. If windows from one person land in both train and test, the model
   is effectively tested on people it has already memorised, and the score
   becomes meaningless. Every split here is **by subject**, and the subject
   lists are explicit.
2. **Leaking the scaler.** A `StandardScaler` fitted on all windows "knows" the
   test set's mean and variance. `fit_scaler` is only ever called with training
   windows, and the API shape makes the other order awkward to write by accident.
3. **Treating a whole ADL recording as one sample.** ADL recordings are 10 s to
   180 s and contain no falls, while a fall recording is 15 s and contains
   exactly one. Comparing them file-to-file confuses "long recording" with
   "activity", so everything is cut into **fixed-length windows** first.

What this module deliberately does NOT do
-----------------------------------------
It does not train, does not touch the network, does not read the database, and
does not know about HTTP. It is a pure function of the archive on disk. That
keeps it usable from a test with no dataset present, and keeps the AI package
free of backend concerns.

Units and orientation
---------------------
SisFall stores **raw ADC integer counts**, not physical units. Columns 1–3 are
the `ADXL345` accelerometer, which the dataset paper itself analyses, so that is
the sensor used here. The Readme gives the conversion

    acceleration [g] = (2 * Range) / (2 ** Resolution) * AD

with `Range = 16 g` and `Resolution = 13` bits for the ADXL345. Converting
matters: without it, a threshold or coefficient has units of "ADC counts", and
the same model cannot be applied to any other sensor.

Features are computed on the **magnitude** as well as the axes. Magnitude is
invariant to how the device is rotated on the body, which is exactly the
variation a real deployment would have and the lab would not.
"""

from __future__ import annotations

import pathlib
import re
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "ADXL345_RANGE_G",
    "ADXL345_RESOLUTION_BITS",
    "ADXL345_G_PER_ADC_BIT",
    "DEFAULT_STRIDE",
    "DEFAULT_WINDOW_ROWS",
    "SAMPLE_RATE_HZ",
    "Window",
    "all_subjects",
    "build_windows",
    "counts_to_g",
    "elderly_subjects",
    "extract_features",
    "feature_matrix",
    "feature_names",
    "fit_scaler",
    "iter_archive_recordings",
    "iter_recordings",
    "parse_recording",
    "read_recording_from_archive",
    "split_subjects",
    "subject_of",
]

# ---------------------------------------------------------------------------
# Fixed properties of the SisFall dataset (from the shipped Readme + paper)
# ---------------------------------------------------------------------------

#: 200 Hz — the Readme states one sample every 5 ms.
SAMPLE_RATE_HZ = 200

#: ADXL345 configured for +/-16 g at 13-bit resolution in SisFall.
ADXL345_RANGE_G = 16.0
ADXL345_RESOLUTION_BITS = 13

#: g per raw ADC count: (2 * 16) / 2**13.
ADXL345_G_PER_ADC_BIT = (2.0 * ADXL345_RANGE_G) / (2.0 ** ADXL345_RESOLUTION_BITS)

#: A fall recording is 15 s (3000 rows); ADL recordings are 10-180 s.
#: A 2 s window is short enough to localise a fall inside a long ADL file, and
#: long enough to contain the impact plus the stillness that follows it.
DEFAULT_WINDOW_ROWS = 2 * SAMPLE_RATE_HZ  # 400 rows = 2.0 s

#: 50 % overlap. More overlap means more windows from a handful of falls, which
#: is the main defence against the dataset's severe class imbalance.
DEFAULT_STRIDE = DEFAULT_WINDOW_ROWS // 2  # 200 rows = 1.0 s

#: Column indices (0-based) of the ADXL345 accelerometer in a SisFall row.
_ADXL_COLUMNS = (0, 1, 2)

_FILENAME_RE = re.compile(r"([DF])(\d{2})_S([AE])(\d{2})_R(\d{2})\.txt$")


# ---------------------------------------------------------------------------
# Recording model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recording:
    """One SisFall file, already parsed and converted to physical units.

    `accel_g` has shape `(n_samples, 3)` in units of g. `subject` is the raw
    subject code such as `SA01` or `SE06`; `cohort` is `"adult"` or `"elderly"`.
    """

    code: str
    subject: str
    cohort: str
    run: str
    label: int
    accel_g: np.ndarray

    @property
    def n_samples(self) -> int:
        return int(self.accel_g.shape[0])

    @property
    def duration_s(self) -> float:
        return self.n_samples / SAMPLE_RATE_HZ


@dataclass(frozen=True)
class Window:
    """A fixed-length slice of one recording, with features already extracted."""

    subject: str
    cohort: str
    code: str
    run: str
    label: int
    #: Index of the first row of this window within its recording.
    start_row: int
    features: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def counts_to_g(counts: np.ndarray) -> np.ndarray:
    """Convert raw ADXL345 ADC counts to g.

    Exposed separately so the conversion is unit-tested against the Readme's
    formula rather than being buried inside the parser.
    """
    return counts * ADXL345_G_PER_ADC_BIT


def parse_recording(text: str) -> np.ndarray:
    """Parse SisFall text into an `(n, 3)` array of **g** for the ADXL345.

    The real files use CRLF line endings, a space-padded integer in every field,
    and terminate each row with `;`. Rows that do not hold exactly nine integers
    are skipped rather than silently coerced, because a mis-parsed row would
    become a fake acceleration spike.

    Only the first three columns (ADXL345) are returned; see the module
    docstring for why that sensor is the one used.
    """
    rows: list[tuple[float, float, float]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(";"):
            line = line[:-1]
        fields = line.split(",")
        if len(fields) != 9:
            continue
        try:
            values = [int(f) for f in fields]
        except ValueError:
            continue
        rows.append(
            (
                float(values[_ADXL_COLUMNS[0]]),
                float(values[_ADXL_COLUMNS[1]]),
                float(values[_ADXL_COLUMNS[2]]),
            )
        )

    if not rows:
        return np.empty((0, 3), dtype=np.float64)

    counts = np.asarray(rows, dtype=np.float64)
    return counts_to_g(counts)


def subject_of(filename: str) -> tuple[str, str]:
    """Return `(subject, cohort)` for a SisFall filename.

    `SA01` -> `("SA01", "adult")`, `SE06` -> `("SE06", "elderly")`.
    Raises `ValueError` for a name that does not match the documented pattern,
    so a mis-named file is caught rather than assigned a wrong subject — which
    would break the subject-wise split and therefore the evaluation.
    """
    match = _FILENAME_RE.search(filename)
    if match is None:
        raise ValueError(
            f"{filename!r} does not match the SisFall filename pattern "
            "'<CODE>_S<A|E><NN>_R<NN>.txt'."
        )
    cohort_letter = match.group(3)
    subject = f"S{cohort_letter}{match.group(4)}"
    cohort = "adult" if cohort_letter == "A" else "elderly"
    return subject, cohort


def _recording_from_text(name: str, text: str) -> Recording | None:
    match = _FILENAME_RE.search(name)
    if match is None:
        return None
    kind, code_num, cohort_letter, subject_num, run = match.groups()
    subject = f"S{cohort_letter}{subject_num}"
    cohort = "adult" if cohort_letter == "A" else "elderly"
    code = kind + code_num
    label = 1 if kind == "F" else 0

    accel_g = parse_recording(text)
    if accel_g.shape[0] == 0:
        return None

    return Recording(
        code=code,
        subject=subject,
        cohort=cohort,
        run=run,
        label=label,
        accel_g=accel_g,
    )


def iter_recordings(
    directory: str | pathlib.Path,
) -> Iterator[Recording]:
    """Yield every recording under an extracted `SisFall_dataset/` directory."""
    root = pathlib.Path(directory)
    for path in sorted(root.rglob("*.txt")):
        if path.name == "Readme.txt" or path.name.startswith("._"):
            continue
        recording = _recording_from_text(path.name, path.read_text(encoding="latin-1"))
        if recording is not None:
            yield recording


def read_recording_from_archive(
    archive: str | pathlib.Path, member: str
) -> Recording | None:
    """Read a single recording out of the original (un-extracted) zip."""
    with zipfile.ZipFile(archive) as zf:
        try:
            raw = zf.read(member)
        except KeyError:
            return None
    return _recording_from_text(member, raw.decode("latin-1"))


def iter_archive_recordings(
    archive: str | pathlib.Path,
    *,
    subjects: Iterable[str] | None = None,
) -> Iterator[Recording]:
    """Stream recordings straight from `SisFall_dataset.zip`.

    Reading from the archive avoids extracting ~230 MB to disk. `__MACOSX`
    entries are skipped; they are AppleDouble metadata, not data.

    `subjects` optionally restricts which subjects are read, which is how a
    subject-wise split is enforced without loading everything.
    """
    wanted = set(subjects) if subjects is not None else None
    with zipfile.ZipFile(archive) as zf:
        names = [
            n
            for n in zf.namelist()
            if n.startswith("SisFall_dataset/")
            and n.endswith(".txt")
            and "/._" not in n
            and not n.endswith("/Readme.txt")
        ]
        for member in sorted(names):
            match = _FILENAME_RE.search(member)
            if match is None:
                continue
            subject = f"S{match.group(3)}{match.group(4)}"
            if wanted is not None and subject not in wanted:
                continue
            recording = _recording_from_text(
                member, zf.read(member).decode("latin-1")
            )
            if recording is not None:
                yield recording


# ---------------------------------------------------------------------------
# Subject inventory and splitting
# ---------------------------------------------------------------------------


def all_subjects(archive: str | pathlib.Path) -> list[str]:
    """Every subject code present in the archive, sorted.

    Derived from the archive itself rather than hard-coded, so the split cannot
    drift away from the data that is actually there.
    """
    with zipfile.ZipFile(archive) as zf:
        subjects = {
            f"S{m.group(3)}{m.group(4)}"
            for n in zf.namelist()
            if n.startswith("SisFall_dataset/") and n.endswith(".txt") and "/._" not in n
            for m in [_FILENAME_RE.search(n)]
            if m is not None
        }
    return sorted(subjects)


def elderly_subjects(archive: str | pathlib.Path) -> list[str]:
    """Subject codes in the elderly cohort (`SE..`)."""
    return [s for s in all_subjects(archive) if s.startswith("SE")]


def subjects_with_falls(archive: str | pathlib.Path) -> set[str]:
    """Subjects who produced at least one fall recording.

    Computed, not assumed. In this dataset it matters: only one elderly subject
    simulated falls, so any elderly test set has to be described honestly as a
    single-subject result.
    """
    found: set[str] = set()
    with zipfile.ZipFile(archive) as zf:
        for n in zf.namelist():
            if not n.startswith("SisFall_dataset/") or not n.endswith(".txt"):
                continue
            if "/._" in n:
                continue
            match = _FILENAME_RE.search(n)
            if match is None or match.group(1) != "F":
                continue
            found.add(f"S{match.group(3)}{match.group(4)}")
    return found


def split_subjects(
    subjects: Sequence[str],
    *,
    test_fraction: float = 0.25,
    seed: int = 20260101,
) -> tuple[list[str], list[str]]:
    """Split **subject codes** into `(train_subjects, test_subjects)`.

    Splitting people, not rows, is the single most important correctness
    property of this module. A deterministic shuffle is used so a rerun gives
    the same split and the reported metrics can be reproduced exactly.

    Both lists are sorted, so the result is stable and easy to read in a log.
    """
    if not subjects:
        raise ValueError("Cannot split an empty subject list.")
    if not 0.0 < test_fraction < 1.0:
        raise ValueError(f"test_fraction must be in (0, 1), got {test_fraction!r}.")

    ordered = sorted(subjects)
    rng = np.random.default_rng(seed)
    shuffled = list(ordered)
    rng.shuffle(shuffled)

    n_test = max(1, round(len(shuffled) * test_fraction))
    # Never let the test set swallow everything.
    n_test = min(n_test, len(shuffled) - 1)
    n_train = len(shuffled) - n_test

    test = sorted(shuffled[:n_test])
    train = sorted(shuffled[n_test : n_test + n_train])
    return train, test


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

#: The feature vector, in a fixed order. Names are part of the contract: the
#: trained model stores this order, and serving must produce the same columns.
_FEATURE_SUFFIXES = (
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
)

_AXES = ("x", "y", "z", "mag")


def feature_names() -> list[str]:
    """The ordered feature names produced by `extract_features`."""
    return [f"{axis}_{suffix}" for axis in _AXES for suffix in _FEATURE_SUFFIXES]


def _axis_features(values: np.ndarray) -> list[float]:
    """Ten time-domain statistics for one 1-D signal.

    Deliberately simple and explainable. A care team can be told "the peak
    acceleration and how much the signal moved" far more credibly than a
    black-box embedding, and the baseline has to be honest before a deep model
    is worth trying.
    """
    if values.size == 0:
        return [0.0] * len(_FEATURE_SUFFIXES)

    mean = float(np.mean(values))
    std = float(np.std(values))
    q1, q3 = np.percentile(values, [25.0, 75.0])
    diffs = np.diff(values)
    # Zero-crossings of the mean-centred signal: a cheap proxy for how
    # oscillatory the window is (walking vs. lying still).
    zero_crossings = (
        float(np.count_nonzero(np.diff(np.signbit(values - mean))))
        if values.size >= 2
        else 0.0
    )
    return [
        mean,
        std,
        float(np.min(values)),
        float(np.max(values)),
        float(np.median(values)),
        float(q3 - q1),
        float(np.sqrt(np.mean(values**2))),
        float(np.max(values) - np.min(values)),
        float(np.mean(np.abs(diffs))) if diffs.size else 0.0,
        zero_crossings,
    ]


def extract_features(accel_g: np.ndarray) -> dict[str, float]:
    """Features for one window of `(n, 3)` accelerometer samples in g.

    Includes the vector magnitude `sqrt(x^2 + y^2 + z^2)`, which does not depend
    on how the sensor was rotated on the body — the main practical difference
    between a lab recording and a real one.
    """
    if accel_g.ndim != 2 or accel_g.shape[1] != 3:
        raise ValueError(
            f"accel_g must have shape (n, 3), got {accel_g.shape!r}."
        )

    magnitude = np.sqrt(np.sum(accel_g**2, axis=1))
    signals = {
        "x": accel_g[:, 0],
        "y": accel_g[:, 1],
        "z": accel_g[:, 2],
        "mag": magnitude,
    }

    features: dict[str, float] = {}
    for axis in _AXES:
        for suffix, value in zip(
            _FEATURE_SUFFIXES, _axis_features(signals[axis]), strict=True
        ):
            features[f"{axis}_{suffix}"] = value
    return features


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------


def build_windows(
    record: Recording,
    *,
    window_rows: int = DEFAULT_WINDOW_ROWS,
    stride: int = DEFAULT_STRIDE,
) -> list[Window]:
    """Cut one recording into overlapping windows with features extracted.

    A short trailing remainder is dropped: a 0.2 s fragment is not a fall
    candidate and would only add noise. Windows are taken with the same length
    and stride for falls and ADLs alike, so neither class gets an easier shape.
    """
    if window_rows <= 0 or stride <= 0:
        raise ValueError("window_rows and stride must be positive.")
    if stride > window_rows:
        raise ValueError("stride must not exceed window_rows.")

    n = record.n_samples
    if n < window_rows:
        return []

    windows: list[Window] = []
    for start in range(0, n - window_rows + 1, stride):
        chunk = record.accel_g[start : start + window_rows]
        windows.append(
            Window(
                subject=record.subject,
                cohort=record.cohort,
                code=record.code,
                run=record.run,
                label=record.label,
                start_row=start,
                features=extract_features(chunk),
            )
        )
    return windows


# ---------------------------------------------------------------------------
# Scaling (fit on training data ONLY)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scaler:
    """A minimal per-feature standardiser.

    Scikit-learn's `StandardScaler` would do, but implementing it here keeps the
    train-only rule visible in the code and keeps this module importable with
    numpy alone. `fit_scaler` is the only way to build one, and it takes exactly
    the training features.
    """

    names: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray

    def transform(self, matrix: np.ndarray) -> np.ndarray:
        return (matrix - self.mean) / self.scale

    def as_dict(self) -> dict[str, list[float]]:
        return {"names": list(self.names), "mean": self.mean.tolist(), "scale": self.scale.tolist()}


def _rows_to_matrix(rows: Sequence[dict[str, float]]) -> np.ndarray:
    """Turn feature dicts into an array in `feature_names()` order.

    A missing feature would otherwise surface as a bare `KeyError: 'x_std'`
    somewhere deep in a training run. Naming the missing feature explicitly turns
    a confusing crash into an obvious one — the usual cause is a caller that
    built features by hand instead of using `extract_features`.
    """
    names = feature_names()
    matrix = np.empty((len(rows), len(names)), dtype=np.float64)
    for i, row in enumerate(rows):
        try:
            for j, name in enumerate(names):
                matrix[i, j] = row[name]
        except KeyError as exc:
            raise ValueError(
                f"Feature {exc.args[0]!r} is missing from row {i}. Every row must "
                "provide all features in feature_names(); use extract_features() "
                "to build them."
            ) from exc
    return matrix


def fit_scaler(feature_rows: Iterable[dict[str, float]]) -> Scaler:
    """Fit a standardiser on the **training** feature rows only.

    Passing test rows here is the classic leak; the parameter name and the
    docstring exist so that mistake is a deliberate act rather than an
    oversight. Zero-variance features get `scale = 1.0` so they do not divide by
    zero (a constant feature simply contributes nothing).
    """
    names = feature_names()
    rows = list(feature_rows)
    if not rows:
        raise ValueError("Cannot fit a scaler on zero feature rows.")

    matrix = _rows_to_matrix(rows)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale == 0.0] = 1.0
    return Scaler(names=tuple(names), mean=mean, scale=scale)


def feature_matrix(windows: Sequence[Window]) -> np.ndarray:
    """Stack window features into an `(n_windows, n_features)` array.

    Column order follows `feature_names()`, which the trained model records.
    """
    return _rows_to_matrix([w.features for w in windows])
