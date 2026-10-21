"""SisFall fall-detection module: preprocess, train, predict.

What lives here
---------------
Three pieces, each with one job:

* `preprocess` — turns the raw SisFall text files into labelled feature
  windows. It owns the unit conversion (raw ADC counts to g), the windowing
  rules, and the **subject-wise split**. Those rules are the part of a fall
  detector that is easy to get quietly wrong, so they live in one testable
  place instead of being re-derived in every script.
* `train` — the training script (`python -m ai.fall_detection.train`). It
  writes the artefacts the predictor loads.
* `predictor` — the serving side. It loads the artefacts and answers "is this
  a fall?" with a `FallDetectionResult`. It never guesses: with no model file
  it reports that the model is missing rather than returning a plausible-
  looking answer.

Import order, and why the imports below are lazy
-----------------------------------------------
`predictor.py` imports the preprocessing module with
`from ai.fall_detection import preprocess as pp`. If this `__init__.py` were to
import `predictor` at module level, the two would form an import cycle:
importing the package would start importing the predictor, which would ask the
package for `preprocess` while the package was still initialising.

Rather than rely on a lucky import order, the public predictor names are
resolved **lazily** through `__getattr__` (PEP 562). `import ai.fall_detection`
therefore does no work beyond loading this file, and
`from ai.fall_detection import FallDetectionPredictor` still works exactly as
before. The cost is one dictionary lookup on first use.

What this module does NOT contain
---------------------------------
No trained model and no dataset. The model file is written by `train.py` into
`ai/models/fall_detection/` and is git-ignored, so a fresh clone reports the
capability as unavailable — which is the honest state, not a bug.

See [`README.md`](README.md) for the dataset, the units, the features, the
split, and the measured results.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["FallDetectionPredictor", "build_predictor"]

#: Public name -> the module that defines it. Kept as data so `__getattr__`
#: stays a couple of lines long and cannot drift out of sync with `__all__`.
_LAZY_EXPORTS: dict[str, str] = {
    "FallDetectionPredictor": "ai.fall_detection.predictor",
    "build_predictor": "ai.fall_detection.predictor",
}


def __getattr__(name: str) -> Any:
    """Resolve the predictor names on first use (PEP 562).

    Keeps the package import cheap and keeps the import graph acyclic: the
    predictor module is only executed when something actually asks for one of
    its names.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = importlib.import_module(module_name)
    value = getattr(module, name)
    # Cache it in the module globals so later look-ups skip this function.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include the lazily exported names in `dir()` for discoverability."""
    return sorted(set(globals()) | set(__all__))
