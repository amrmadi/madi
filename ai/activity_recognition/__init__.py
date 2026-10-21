"""Activity recognition — **planned, not trained**.

What this package is for
------------------------
The second of the three problems the project set out to solve: classify what
a person is doing right now — walking, standing, sitting, lying, eating,
sleeping, toileting — from sensor data.

The planned dataset is **UCI HAR** (see
[`docs/datasets/uci-har.md`](../../docs/datasets/uci-har.md)), which is
documented before it is downloaded.

Current state — read this before assuming anything
--------------------------------------------------
* **There is no model.** No dataset has been downloaded, no model has been
  trained, and no model file exists.
* **There is no model file in this repository**, and none will be committed:
  trained artefacts are git-ignored.
* The API answers **`503 MODEL_NOT_LOADED`** for this capability. That is
  the honest response: the service is reachable, the capability genuinely is
  not available yet.
* `ai/registry.py` therefore returns an `UnavailablePredictor` for
  `"activity_recognition"`. It reports `is_ready: false` and `metrics: null`,
  and its `predict()` raises `ModelNotLoadedError` rather than returning a
  plausible-looking guess.

There are **no accuracy, precision or recall numbers for this capability**,
and none are invented anywhere in this repository.

The intended interface
----------------------
When this package is built it will follow the same three-file shape as
[`../fall_detection/`](../fall_detection):

```
ai/activity_recognition/
    __init__.py
    preprocess.py   # parse UCI HAR -> feature windows, subject-wise split
    train.py        # python -m ai.activity_recognition.train
    predictor.py    # loads the artefacts, returns an ActivityResult
    README.md
```

The predictor will implement the `Predictor` protocol from
[`../base.py`](../base.py):

* `info` -> a `ModelInfo` carrying the **measured** metrics, or `metrics:
  None` when nothing has been evaluated.
* `is_ready()` -> `True` only when a trained model file is present and
  loadable.
* `predict(features)` -> an `ActivityResult`, or `ModelNotLoadedError` when
  there is no model.

An `ActivityResult` (`ai/base.py`) carries the top class as `activity`, the
probability as `confidence`, the full per-class distribution as `scores`, and
exposes `is_ambiguous` — True when the two best classes are within 0.10 of
each other. That last property exists so the UI can show "not sure" instead
of a confident-looking label the model did not actually have.

The rules this capability must follow when it is built
------------------------------------------------------
1. **Never present simulated data as real.** UCI HAR is other people's data,
   so every result derived from it is flagged `is_simulated: true`.
2. **An unavailable capability says so.** Until a model exists, the answer is
   `503 MODEL_NOT_LOADED`, never a guess.
3. **Split by subject, never by row**, and fit the scaler on the training
   windows only — the same rule `ai/fall_detection/preprocess.py` exists to
   enforce.
4. **Report only measured metrics,** on a held-out split, in the README
   next to the code.

See [`README.md`](README.md) for the full plan.
"""

from __future__ import annotations

#: Nothing is exported yet, and that is deliberate: there is no trained model
#: and no public API to offer. The names will appear here when the predictor
#: is written.
__all__: list[str] = []
