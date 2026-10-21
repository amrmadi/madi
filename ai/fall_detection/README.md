# Fall detection (SisFall)

A windowed accelerometer model that answers one question: **is this a fall?**

The answer is a detection prompt for a caregiver, never a medical finding.
Every prediction is flagged `is_simulated: true`, because SisFall was recorded
from unrelated volunteers and is not a reading of any resident of this
system.

---

## Contents

- [Goal](#goal)
- [The dataset](#the-dataset)
- [The sensor and the units](#the-sensor-and-the-units)
- [Windowing](#windowing)
- [Features (40)](#features-40)
- [The split — subjects, never rows](#the-split--subjects-never-rows)
- [The model](#the-model)
- [Measured results](#measured-results)
- [Honesty caveats](#honesty-caveats)
- [Reproducing](#reproducing)
- [Files](#files)

---

## Goal

Detect a fall from a short burst of tri-axial accelerometer data, on a
budget of about 40 explainable numbers per window, and say so honestly when
the model has not been trained.

---

## The dataset

**SisFall** — a public fall-detection dataset of simulated falls and
activities of daily living, recorded with a chest-mounted sensor.

| Property | Value |
|---|---|
| Source, size, checksum | [`docs/datasets/sisfall.md`](../../docs/datasets/sisfall.md) |
| Sampling rate | 200 Hz (one sample every 5 ms) |
| Subjects | adults (`SA..`) and elderly (`SE..`) volunteers |
| Recording types | falls (`F..`) and activities of daily living (`D..`) |
| Lengths | a fall recording is 15 s; ADL recordings run 10 s – 180 s |
| In this repository | **Not committed.** It is git-ignored and downloaded by hand. |

The dataset is **not** committed to this repository (roughly 220 MB). The
source URL, the exact byte size, the checksum and the format notes are in
[`docs/datasets/sisfall.md`](../../docs/datasets/sisfall.md), which is written
before the data is used.

---

## The sensor and the units

SisFall stores **raw ADC integer counts**, not physical units, so the first
thing the preprocessing does is convert them.

Only the **ADXL345** accelerometer is used — columns 1–3 of each row. It is
the sensor the dataset paper itself analyses, and it is configured for
**±16 g at 13-bit resolution**.

The dataset Readme gives the conversion:

```
acceleration [g] = (2 * Range) / (2 ** Resolution) * AD
```

with `Range = 16 g` and `Resolution = 13`, so one ADC count is

```
2 * 16 / 2**13 = 32 / 8192 = 0.00390625 g
```

This is implemented once, in `preprocess.counts_to_g`, and unit-tested against
the formula rather than being buried inside the parser.

**Why it matters.** Without the conversion, every threshold and coefficient
would carry the units "ADC counts", and the model could not be applied to any
other sensor. With it, the features are physical quantities a caregiver can be
shown: peak acceleration in g, movement in g/s, and so on.

---

## Windowing

A recording is not a sample. ADL recordings are ten to a hundred and eighty
seconds long and contain no fall at all, while a fall recording is fifteen
seconds long and contains exactly one. Comparing them file-to-file would
confuse *recording length* with *activity*.

Everything is therefore cut into fixed-length windows:

| Setting | Value | Meaning |
|---|---|---|
| Window length | **400 rows = 2.0 s** | Short enough to localise a fall inside a long ADL file, long enough to contain the impact and the stillness that follows it. |
| Stride | **200 rows = 1.0 s** | 50 % overlap. More overlap means more windows from a handful of falls, which is the main defence against the dataset's severe class imbalance. |
| Trailing remainder | dropped | A 0.2 s fragment is not a fall candidate. |

Falls and ADLs are windowed identically, so neither class gets an easier
shape.

---

## Features (40)

Ten time-domain statistics for each of four signals — `x`, `y`, `z` and the
vector magnitude `mag = sqrt(x² + y² + z²)`:

```
mean, std, min, max, median, iqr, rms, range, mean_abs_diff, zero_crossings
```

4 × 10 = **40 features**, in a fixed order (`preprocess.feature_names()`).
The order is part of the contract: the trained artefact records it, and
serving has to produce the same columns.

`mag` is included because it does not depend on how the device was rotated on
the body — which is exactly the variation a real deployment has and a lab
recording does not.

The features are deliberately simple and explainable. A care team can be told
"the peak acceleration was 4.2 g and the signal was still afterwards" far more
credibly than they can be told about a black-box embedding.

---

## The split — subjects, never rows

This is the part of the pipeline that is easy to get quietly wrong, because a
wrong split does not crash: it just produces a number that flatters the model.

SisFall records each volunteer for many seconds at 200 Hz. If windows from one
person land in both the training and the test set, the model is effectively
tested on people it has already memorised, and the score becomes meaningless.

So:

- The split is over **subject codes**, never rows. `preprocess.split_subjects`
  is the only way to make it, and it returns two disjoint, sorted lists.
- The training script prints **both subject lists in full**, so the split can
  be checked by eye.
- The scaler is fitted on the **training windows only**
  (`preprocess.fit_scaler`). A scaler fitted on everything "knows" the test
  set's mean and variance, and the resulting score is quietly optimistic.
- A constant feature gets `scale = 1.0` rather than zero, so nothing divides
  by zero at serving time.

---

## The model

A `sklearn.ensemble.RandomForestClassifier`:

| Setting | Value | Why |
|---|---|---|
| `n_estimators` | 300 | Enough trees for a stable probability without being slow. |
| `class_weight` | `"balanced_subsample"` | SisFall is heavily imbalanced — there are far more ordinary-activity windows than fall windows. Without this the forest learns to say "no fall" and scores well on accuracy alone. |
| `random_state` | the `--seed` value | A rerun reproduces the same forest. |

The operating threshold (default `0.5`) turns the model's probability into a
yes/no decision. The training script prints a sweep of thresholds so the
trade-off between precision and recall is visible rather than hidden behind a
single number.

---

## Measured results

> **F1 0.80 on 6 unseen adult subjects (SisFall).**

Read that carefully, because most of it is a caveat:

- **Measured on the author's machine**, on the training run that produced the
  code committed in this repository.
- **The dataset and the trained model file are not committed** (both are
  git-ignored), so **a fresh clone cannot reproduce these numbers** without
  re-downloading the dataset and re-running the training script. The split
  depends on the subject list of the archive and on the seed.
- **The exact precision and recall of that run were not recorded in this
  repository**, so they are not stated here. Inventing them would be worse
  than omitting them. Run the training script and it prints the full,
  measured set — precision, recall, F1, accuracy, the fall/no-fall support
  counts, and the threshold sweep — for whatever split your machine
  produces.
- **The elderly result rests on a single subject.** Only one elderly
  volunteer in SisFall simulated a fall, so any "elderly" number describes
  that one person's recordings. It is **not** an estimate of performance on
  elderly people in general, and it must never be quoted as one.

The training script reports the elderly subset separately, with the same
caveat attached, and **omits** the elderly metrics entirely when the held-out
split happens to contain no elderly fall windows — a number that cannot be
measured is not reported as zero.

---

## Honesty caveats

- **A predicted fall is not a medical finding.** The result carries
  `not_a_medical_assessment: true` and every positive result requires human
  review.
- **Every result is flagged `is_simulated: true`.** SisFall is other people's
  data; it is never a reading of a resident of this system.
- **The model file is not committed.** A fresh clone reports
  `is_ready: false` and `metrics: null`. That is the honest state, not a bug.
- **An unavailable capability says so.** With no model file, `predict()`
  raises `ModelNotLoadedError`, which the API turns into
  `503 MODEL_NOT_LOADED` — never into a made-up answer.
- **The elderly figure is a single-subject result** (see above).
- **This is a baseline, not a product.** It has been evaluated on lab
  recordings of simulated falls, on one public dataset, at one threshold. It
  has not been evaluated on real falls, on real deployments, or on the
  hardware this system would actually use.

---

## Reproducing

### 1. Get the dataset

Download `SisFall_dataset.zip` and place it at `data/raw/SisFall_dataset.zip`.
The source, the byte size and the checksum are in
[`docs/datasets/sisfall.md`](../../docs/datasets/sisfall.md).

### 2. Install the training dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install scikit-learn joblib
```

`numpy` is the only thing needed to import the package; `scikit-learn` and
`joblib` are needed to train.

### 3. Train

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m ai.fall_detection.train
```

which is exactly this, with the defaults spelled out:

```powershell
.\.venv\Scripts\python.exe -m ai.fall_detection.train `
    --archive data/raw/SisFall_dataset.zip `
    --output-dir ai/models/fall_detection `
    --test-fraction 0.25 `
    --seed 20260101 `
    --model-version fall-rf-v1 `
    --threshold 0.5
```

The script prints the subject lists, the measured metrics, the elderly
evaluation with its caveat, the threshold sweep, and the paths it wrote. It
exits non-zero with an actionable message if the archive is missing — it never
substitutes synthetic data for the real one.

`--help` works without the dataset present:

```powershell
.\.venv\Scripts\python.exe -m ai.fall_detection.train --help
```

### 4. Load the trained model

```python
from ai.registry import get_predictor

predictor = get_predictor("fall_detection")
if not predictor.is_ready():
    raise SystemExit("No trained model. Run: python -m ai.fall_detection.train")

# 500 samples (2.5 s at 200 Hz) of accelerometer triples in g.
result = predictor.predict([[0.0, 0.0, 1.0]] * 500)

print(result.is_fall, result.confidence, result.explanation)
print(result.is_simulated)   # True: research data, never a resident reading
```

The artefacts written by the training script are:

| File | Contents |
|---|---|
| `ai/models/fall_detection/fall-rf-v1.joblib` | The fitted estimator, the scaler statistics, the feature order, the threshold, and the metadata. Git-ignored. |
| `ai/models/fall_detection/fall-rf-v1.json` | The same metadata as plain JSON, readable without unpickling. Git-ignored. |

---

## Files

| File | Role |
|---|---|
| [`preprocess.py`](preprocess.py) | Parsing, unit conversion, windowing, features, the subject-wise split, the train-only scaler. |
| [`train.py`](train.py) | The training script: `python -m ai.fall_detection.train`. |
| [`predictor.py`](predictor.py) | The serving side: loads the artefacts and returns a `FallDetectionResult`. |
| [`../base.py`](../base.py) | The shared result types and the `Predictor` protocol. |
| [`../registry.py`](../registry.py) | Hands the backend a predictor by name. |
| [`../tests/`](../tests) | Tests for the result types, the registry, the preprocessing and the predictor. |
