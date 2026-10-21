"""Behavioural analysis — **planned, not trained**.

What this package is for
------------------------
The third of the three problems the project set out to solve: notice when a
resident's routine departs from **their own** baseline — a day where
something that normally happens did not happen, or happened far more often
than usual.

The planned dataset is **CASAS** (see
[`docs/datasets/casas.md`](../../docs/datasets/casas.md)), which is documented
before it is downloaded.

Current state — read this before assuming anything
--------------------------------------------------
* **There is no model.** No dataset has been downloaded, no model has been
  trained, and no model file exists.
* **There is no model file in this repository**, and none will be committed:
  trained artefacts are git-ignored.
* The API answers **`503 MODEL_NOT_LOADED`** for this capability.
* `ai/registry.py` therefore returns an `UnavailablePredictor` for
  `"anomaly_detection"`. It reports `is_ready: false` and `metrics: null`,
  and its `predict()` raises `ModelNotLoadedError` rather than returning a
  plausible-looking guess.

There are **no accuracy, precision, recall or false-positive numbers for this
capability**, and none are invented anywhere in this repository.

What this capability is *not*
-----------------------------
**It is not a medical diagnosis and must never be described as one.** A
routine change is frequently benign — a bad night's sleep, a visitor, a
different day of the week. This capability answers "is this unusual *for this
person*?", nothing more. The word "anomaly" in the API is a technical label
for a statistical deviation, not a clinical finding.

The intended interface
----------------------
When this package is built it will follow the same three-file shape as
[`../fall_detection/`](../fall_detection):

```
ai/behavioral_analysis/
    __init__.py
    preprocess.py   # parse CASAS -> daily routine features, per-resident split
    train.py        # python -m ai.behavioral_analysis.train
    predictor.py    # loads the artefacts, returns an AnomalyResult
    README.md
```

The predictor will implement the `Predictor` protocol from
[`../base.py`](../base.py):

* `info` -> a `ModelInfo` carrying the **measured** metrics, or `metrics:
  None` when nothing has been evaluated.
* `is_ready()` -> `True` only when a trained model file is present and
  loadable.
* `predict(features)` -> an `AnomalyResult`, or `ModelNotLoadedError` when
  there is no model.

An `AnomalyResult` (`ai/base.py`) carries `is_anomaly`, a dimensionless
`deviation_score`, an explicit `direction` (`above`, `below` or `none`), and
`deviating_features` — the explainability payload, so a caregiver can see
*what* changed and not merely that "something did".

See [`README.md`](README.md) for the full plan.
"""

from __future__ import annotations

#: Nothing is exported yet, and that is deliberate: there is no trained model
#: and no public API to offer. The names will appear here when the predictor
#: is written.
__all__: list[str] = []
