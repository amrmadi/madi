# Activity recognition (planned — **not trained**)

> **Status: NOT TRAINED. There is no model file, and no accuracy number
> exists for this capability.**
>
> The API answers **`503 MODEL_NOT_LOADED`** for `activity_recognition`, and
> `GET /api/v1/ai/predictors` reports it as `is_ready: false` with
> `metrics: null`. That is the intended behaviour, not a bug.

---

## Contents

- [What this capability is for](#what-this-capability-is-for)
- [The planned dataset](#the-planned-dataset)
- [Current state](#current-state)
- [The intended interface](#the-intended-interface)
- [The intended file layout](#the-intended-file-layout)
- [How it would be built](#how-it-would-be-built)
- [What "done" means for this capability](#what-done-means-for-this-capability)
- [Honesty rules this capability must follow](#honesty-rules-this-capability-must-follow)

---

## What this capability is for

The second of the three AI problems in ElderLife AI: **classify daily
activities** — walking, standing, sitting, lying, eating, sleeping,
toileting — from sensor data, so a caregiver can see how a resident's day
actually went rather than only seeing alarms.

---

## The planned dataset

**UCI HAR** — the Human Activity Recognition Using Smartphones dataset:
~10,000 recordings of 30 volunteers performing six activities (walking,
walking upstairs, walking downstairs, sitting, standing, lying) with a
waist-mounted phone accelerometer and gyroscope, plus a per-person activity
label for every time slice.

| Property | Value |
|---|---|
| Source, size, checksum, format | [`docs/datasets/uci-har.md`](../../docs/datasets/uci-har.md) |
| Sensors | phone accelerometer (50 Hz) and gyroscope |
| Labels | six activities, per labelled time window |
| In this repository | **Not downloaded.** The dataset is git-ignored. |

The dataset documentation is written **before** the data is downloaded, so the
source URL, the exact byte size, the checksum, the file format and the label
mapping are all recorded up front. See
[`docs/datasets/uci-har.md`](../../docs/datasets/uci-har.md).

---

## Current state

| Question | Answer |
|---|---|
| Is a model trained? | **No.** |
| Is there a model file? | **No.** Trained artefacts are git-ignored; none are committed. |
| Is the dataset downloaded? | **No.** |
| Are there accuracy / precision / recall numbers? | **No.** None are measured, and none are invented anywhere in this repository. |
| What does the API return? | **`503 MODEL_NOT_LOADED`** for `POST /api/v1/ai/predictors/activity_recognition/check`. |
| What does `GET /api/v1/ai/predictors` report? | `is_ready: false`, `model_version: null`, `trained_at: null`, `metrics: null`, `dataset: "UCI HAR"`. |

`ai/registry.py` returns an `UnavailablePredictor` for this name. That object
implements the same `Predictor` protocol as a real one, so the backend does
not need special-casing — but its `predict()` always raises
`ModelNotLoadedError`, which the API converts into the honest 503.

---

## The intended interface

The predictor will implement the `Predictor` protocol from
[`../base.py`](../base.py):

```python
from ai.base import ActivityResult, ModelInfo, ModelNotLoadedError, Predictor
```

| Member | Contract |
|---|---|
| `info` -> `ModelInfo` | The **measured** metrics of the trained model, or `metrics: None` when nothing has been evaluated. Never placeholder numbers. |
| `is_ready() -> bool` | `True` only when a trained model file is present and loadable. `False` otherwise. |
| `predict(features) -> ActivityResult` | The classification. Raises `ModelNotLoadedError` when `is_ready()` is `False`. |

The result type is [`ActivityResult`](../base.py):

| Field | Meaning |
|---|---|
| `activity` | The most likely activity (`walking`, `standing`, `sitting`, `lying`, `eating`, `sleeping`, `toileting`, `unknown`). |
| `confidence` | The model's probability for that class, 0.0–1.0. |
| `scores` | The full per-class distribution, when the model provides one. |
| `is_ambiguous` | `True` when the two best classes are within 0.10 of each other — the model was undecided, and the UI should say so instead of showing a confident-looking label. |
| `source` | Where the input came from. A result derived from UCI HAR is `imported_dataset`, which makes `is_simulated` `True`. |
| `explanation` | Why the model answered this way. Required: an unexplained prediction is not usable in a care setting. |

Keeping the whole distribution in `scores` matters, because "60 % walking,
38 % standing" is a very different situation from "99 % walking" — and only
the first one should raise a question.

---

## The intended file layout

Mirroring [`../fall_detection/`](../fall_detection), which is the reference
implementation in this package:

```
ai/activity_recognition/
    __init__.py       # package docstring and public exports
    preprocess.py     # parse UCI HAR -> feature windows, subject-wise split
    train.py          # python -m ai.activity_recognition.train
    predictor.py      # loads the artefacts, returns an ActivityResult
    README.md         # this file
```

---

## How it would be built

1. **Document the dataset first.** `docs/datasets/uci-har.md` records the
   source, the size, the checksum, the format and the label mapping *before*
   the download happens.
2. **Preprocess into windows.** UCI HAR is already cut into ~2.56 s time
   slices with a label each, so the windowing job is smaller than for
   SisFall — but the per-person split still has to be enforced.
3. **Split by subject, never by row.** UCI HAR has 30 volunteers; a row-wise
   split would put the same person on both sides and flatter the score. The
   scaler is fitted on the training windows only.
4. **Train a simple baseline first** (a RandomForest over per-window time and
   frequency features, in the style of `ai/fall_detection`), measure it on
   the held-out people, and only then consider something larger.
5. **Write the measured metrics into this README**, next to the code, with
   the caveat that they come from a lab dataset of 30 volunteers and are not
   a claim about elderly people in their own homes.

---

## What "done" means for this capability

Taken from the project's task list ([`CONTRIBUTING.md`](../../CONTRIBUTING.md)):

> **Done when:** the model is evaluated on a held-out split, its measured
> metrics are written into a README next to the code, and the API serves it.

Until then, this capability stays reported as unavailable.

---

## Honesty rules this capability must follow

These are the project's rules, not suggestions:

1. **Never present simulated data as real.** UCI HAR is other people's
   recordings. Every result derived from it is flagged
   `is_simulated: true`, so it can never be shown as a resident's own reading.
2. **An unavailable capability says so.** Until a model exists: `503
   MODEL_NOT_LOADED`, `is_ready: false`, `metrics: null`. Never a guess.
3. **A missing measurement is not an emergency.** An unrecognised activity is
   "unknown", not an alert.
4. **Report only measured metrics**, on a held-out split of **people**, in
   this file.
5. **No secrets, no personal data.** UCI HAR contains no personal data and
   the dataset stays outside version control.
