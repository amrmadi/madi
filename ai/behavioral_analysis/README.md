# Behavioural analysis (planned — **not trained**)

> **Status: NOT TRAINED. There is no model file, and no accuracy, threshold
> or false-positive number exists for this capability.**
>
> The API answers **`503 MODEL_NOT_LOADED`** for `anomaly_detection`, and
> `GET /api/v1/ai/predictors` reports it as `is_ready: false` with
> `metrics: null`. That is the intended behaviour, not a bug.

---

## Contents

- [What this capability is for](#what-this-capability-is-for)
- [What it is not](#what-it-is-not)
- [The planned dataset](#the-planned-dataset)
- [Current state](#current-state)
- [The intended interface](#the-intended-interface)
- [The intended file layout](#the-intended-file-layout)
- [How it would be built](#how-it-would-be-built)
- [What "done" means for this capability](#what-done-means-for-this-capability)
- [Honesty rules this capability must follow](#honesty-rules-this-capability-must-follow)

---

## What this capability is for

The third of the three AI problems in ElderLife AI: **flag an unusual
routine for a resident, measured against their own baseline.**

The reference point is the person, not the population. A resident who normally
goes to bed at 22:00 and is still up at 01:00 is worth a look; a neighbour
with the same habit is not. So the model is a *per-resident* baseline, and
the score answers "does today look like this person's normal day?".

---

## What it is not

**This is not a medical diagnosis, and must never be described as one.**

A routine change is frequently benign: a bad night's sleep, a visitor, a
different day of the week, a hospital appointment. The output is a prompt
for a human to look, with the deviating features named so the human can see
whether the change looks worrying. Nothing more.

Two related rules follow from that:

- A deviation is **not** automatically an alert, and an alert raised from it
  must carry a severity that is an **operational triage priority**, not a
  medical risk score.
- A **missing measurement is not an emergency**. A day with no recorded
  activity is "no data", not "something is wrong".

---

## The planned dataset

**CASAS** — the Change Detection and Activity Monitoring (CASAS) smart-home
benchmark: simulated and recorded household activity sequences over sensors
such as motion, door and temperature sensors.

| Property | Value |
|---|---|
| Source, size, checksum, format | [`docs/datasets/casas.md`](../../docs/datasets/casas.md) |
| Content | household sensor readings over days and weeks |
| In this repository | **Not downloaded.** The dataset is git-ignored. |

The dataset documentation is written **before** the data is downloaded, so the
source URL, the exact byte size, the checksum, the file format and the sensor
layout are all recorded up front. See
[`docs/datasets/casas.md`](../../docs/datasets/casas.md).

---

## Current state

| Question | Answer |
|---|---|
| Is a model trained? | **No.** |
| Is there a model file? | **No.** Trained artefacts are git-ignored; none are committed. |
| Is the dataset downloaded? | **No.** |
| Are there accuracy / false-positive numbers? | **No.** None are measured, and none are invented anywhere in this repository. |
| Is there a threshold? | **No.** A threshold is only meaningful once it has been measured against a known false-positive rate. |
| What does the API return? | **`503 MODEL_NOT_LOADED`** for `POST /api/v1/ai/predictors/anomaly_detection/check`. |
| What does `GET /api/v1/ai/predictors` report? | `is_ready: false`, `model_version: null`, `trained_at: null`, `metrics: null`, `dataset: "CASAS"`. |

`ai/registry.py` returns an `UnavailablePredictor` for this name. That object
implements the same `Predictor` protocol as a real one, so the backend does
not need special-casing — but its `predict()` always raises
`ModelNotLoadedError`, which the API converts into the honest 503.

---

## The intended interface

The predictor will implement the `Predictor` protocol from
[`../base.py`](../base.py):

```python
from ai.base import AnomalyResult, ModelInfo, ModelNotLoadedError, Predictor
```

| Member | Contract |
|---|---|
| `info` -> `ModelInfo` | The **measured** metrics of the trained model, or `metrics: None` when nothing has been evaluated. Never placeholder numbers. |
| `is_ready() -> bool` | `True` only when a trained model file is present and loadable. `False` otherwise. |
| `predict(features)` -> `AnomalyResult` | The deviation assessment. Raises `ModelNotLoadedError` when `is_ready()` is `False`. |

The result type is [`AnomalyResult`](../base.py):

| Field | Meaning |
|---|---|
| `is_anomaly` | True when the routine departs from the person's own baseline. |
| `deviation_score` | A dimensionless distance from the baseline. The scale is model-defined and is documented by the producing model, not assumed here. |
| `direction` | `above`, `below` or `none`. An unusually **quiet** day can matter as much as an unusually busy one, so the direction is recorded explicitly rather than inferred from the sign of the score. `direction="none"` with a non-empty `deviating_features` is rejected by the type. |
| `deviating_features` | Which baseline features moved, and by how much — the explainability payload. |
| `explanation` | Why the model answered this way. Required: an unexplained prediction is not usable in a care setting. |

---

## The intended file layout

Mirroring [`../fall_detection/`](../fall_detection), which is the reference
implementation in this package:

```
ai/behavioral_analysis/
    __init__.py       # package docstring and public exports
    preprocess.py     # parse CASAS -> daily routine features, per-resident split
    train.py          # python -m ai.behavioral_analysis.train
    predictor.py      # loads the artefacts, returns an AnomalyResult
    README.md         # this file
```

---

## How it would be built

1. **Document the dataset first.** `docs/datasets/casas.md` records the
   source, the size, the checksum, the format and the sensor layout *before*
   the download happens.
2. **Build a per-resident baseline.** The natural first approach, as the
   project task list suggests, is a per-resident routine baseline — an
   `IsolationForest`, or simple statistics over activity sequences — fitted
   on that resident's own normal days. A model fitted on everyone's data
   would answer "is this day normal for people", which is a different and
   much weaker question.
3. **Split by resident, never by row**, and fit every statistic on the
   training residents only.
4. **Choose the threshold by measurement, not by taste.** The operating
   point has to be picked against a **stated false-positive rate** — how
   often a normal day gets flagged. A threshold with no false-positive rate
   attached is not a usable threshold.
5. **Report it honestly.** The measured false-positive rate, the threshold,
   the metrics and the caveats all go in this file, next to the code.

---

## What "done" means for this capability

Taken from the project's task list ([`CONTRIBUTING.md`](../../CONTRIBUTING.md)):

> **Done when:** it produces a score with a stated threshold and a documented
> false-positive rate. Do **not** report an accuracy number you did not
> measure, and do not describe the output as a medical diagnosis.

Until then, this capability stays reported as unavailable.

---

## Honesty rules this capability must follow

These are the project's rules, not suggestions:

1. **Never present simulated data as real.** CASAS is research data, so any
   result derived from it is flagged `is_simulated: true`.
2. **An unavailable capability says so.** Until a model exists: `503
   MODEL_NOT_LOADED`, `is_ready: false`, `metrics: null`. Never a guess.
3. **A missing measurement is not an emergency.** No data is not a deviation.
4. **Never describe the output as a medical diagnosis**, and never let an
   alert severity derived from it be read as a medical risk score.
5. **Report only measured metrics**, with a **stated threshold and a
   documented false-positive rate**, in this file.
6. **No secrets, no personal data.** The dataset stays outside version
   control, and no resident's records are ever committed.
