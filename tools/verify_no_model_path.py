"""Prove that the AI layer never invents a model, a metric or a prediction.

Why this validator exists
-------------------------
The project's honesty rule is simple to state and easy to break by accident:

    A capability that has no trained model must say so. It must not return a
    plausible-looking number, and it must not report evaluation metrics that
    were never measured.

Nothing enforces that rule at runtime. A predictor that returns
`confidence=0.87` because someone typed it in would look perfectly normal in
the API, in the UI and in a report. The only defence is to check the source
mechanically, which is what this script does.

Two halves
----------
**Behaviour.** The registry is imported and every predictor is asked the same
three questions:

* `is_ready()` — is a trained model actually loaded?
* `info.metrics` — are there measured evaluation metrics, or `None`?
* `predict(...)` — does it raise `ModelNotLoadedError` rather than guessing?

**Source.** Every Python file under `ai/` is parsed with `ast` and searched
for the four ways the rule gets broken:

* an absolute path baked into the source (`C:\\...`, `/home/...`), which would
  make the model artefacts machine-specific;
* a `predict`-like function that returns a float literal;
* a literal value for a metric such as `precision`, `recall`, `f1`,
  `accuracy`, `auc` or `rmse`;
* an `is_ready()` that ignores whether the model file exists.

The check is offline: no database, no network and no dataset are needed, and
nothing is downloaded or trained.

Run it with:

    python tools/verify_no_model_path.py
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AI_DIR = REPO_ROOT / "ai"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: The three problems the project set out to solve. Every one of them must be
#: reachable through the registry.
EXPECTED_PREDICTORS = ("fall_detection", "activity_recognition", "anomaly_detection")

#: Where a trained fall-detection model would live. It is git-ignored, and it
#: does not exist in a fresh checkout.
MODEL_DIR = AI_DIR / "models"

#: Function names that produce a prediction. A hard-coded number returned from
#: one of these is a fabricated answer.
PREDICT_LIKE_PREFIXES = ("predict", "classify", "infer")

#: Metric names whose value must come from a real evaluation run.
METRIC_NAMES = frozenset(
    {
        "precision",
        "recall",
        "f1",
        "f1_score",
        "accuracy",
        "auc",
        "roc_auc",
        "rmse",
        "mse",
        "mae",
    }
)

#: Absolute paths that must never be hard-coded. `Path(__file__).resolve()`
#: is the only acceptable way to locate something.
ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:[A-Za-z]:[\\/]{1,2}|\\\\[A-Za-z0-9_.-]+[\\/]|"
    r"/(?:home|Users|mnt|opt|srv|root)/)"
)

#: Markers of a file-existence check inside `is_ready()`.
EXISTENCE_MARKERS = (".exists(", ".is_file(", "os.path.exists", "pathlib.Path")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@dataclass
class Report:
    """Collects check outcomes so the script can print one tidy summary."""

    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def ok(self, message: str) -> None:
        """Record a passing check."""
        self.passed.append(message)

    def fail(self, message: str) -> None:
        """Record a failing check."""
        self.failed.append(message)

    def check(self, condition: bool, success: str, failure: str) -> bool:
        """Record a check and return its outcome."""
        if condition:
            self.ok(success)
        else:
            self.fail(failure)
        return bool(condition)


# ---------------------------------------------------------------------------
# Behavioural checks
# ---------------------------------------------------------------------------


def check_registry(report: Report) -> None:
    """Import the registry and interrogate every predictor it hands out."""
    from ai.base import ModelNotLoadedError
    from ai.registry import AVAILABLE_PREDICTORS, get_predictor

    for name in EXPECTED_PREDICTORS:
        report.check(
            name in AVAILABLE_PREDICTORS,
            f"the registry declares the {name!r} predictor",
            f"the registry does not declare the {name!r} predictor; "
            f"it declares {sorted(AVAILABLE_PREDICTORS)}",
        )

    for name in EXPECTED_PREDICTORS:
        if name not in AVAILABLE_PREDICTORS:
            continue

        try:
            predictor = get_predictor(name)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report.fail(f"get_predictor({name!r}) raised {exc!r}")
            continue

        report.ok(f"get_predictor({name!r}) returned {type(predictor).__name__}")

        # -- is_ready() must be False while no model is loaded --------------
        try:
            ready = predictor.is_ready()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report.fail(f"{name}.is_ready() raised {exc!r}")
            ready = None

        if ready is not None:
            report.check(
                ready is False,
                f"{name}.is_ready() is False (no trained model is loaded)",
                f"{name}.is_ready() returned {ready!r}; no trained model file "
                "is present, so it must report False",
            )

        # -- metrics must be None, never a placeholder ----------------------
        info = predictor.info
        metrics = getattr(info, "metrics", None)
        report.check(
            metrics is None,
            f"{name}.info.metrics is None (nothing was measured)",
            f"{name}.info.metrics is {metrics!r}; without a trained model "
            "there are no measured metrics and placeholders are forbidden",
        )

        # -- predict() must refuse rather than guess ------------------------
        try:
            predictor.predict([])
        except ModelNotLoadedError:
            report.ok(
                f"{name}.predict() raised ModelNotLoadedError instead of "
                "returning a guess"
            )
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report.fail(
                f"{name}.predict() raised {type(exc).__name__} instead of "
                f"ModelNotLoadedError: {exc}"
            )
        else:
            report.fail(
                f"{name}.predict() returned a value; a predictor with no model "
                "must raise ModelNotLoadedError"
            )


def check_model_directory(report: Report) -> None:
    """Report the state of the git-ignored model directory."""
    if MODEL_DIR.exists():
        artefacts = sorted(
            path.name for path in MODEL_DIR.rglob("*") if path.is_file()
        )
        report.ok(
            f"{MODEL_DIR.relative_to(REPO_ROOT)} exists and holds "
            f"{len(artefacts)} file(s); trained artefacts are git-ignored"
        )
    else:
        report.ok(
            f"{MODEL_DIR.relative_to(REPO_ROOT)} does not exist, so no "
            "predictor can claim to be ready"
        )


# ---------------------------------------------------------------------------
# Static source checks
# ---------------------------------------------------------------------------


def python_files() -> list[Path]:
    """Return every Python file under `ai/`."""
    return sorted(AI_DIR.rglob("*.py"))


def is_abstract(body: list[ast.stmt]) -> bool:
    """True when a function body is only a docstring, `...`, or `pass`.

    A docstring does not make a body concrete. A `Protocol` method such as
    `Predictor.is_ready` has one, and its body is still just `...` — the
    method is a contract, not an implementation, so it cannot be expected to
    check whether a model file exists.
    """
    statements = list(body)

    # Drop a leading docstring: it documents the method without implementing it.
    if statements and isinstance(statements[0], ast.Expr):
        value = statements[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            statements.pop(0)

    for statement in statements:
        if isinstance(statement, ast.Expr) and isinstance(
            statement.value, ast.Constant
        ):
            if statement.value.value is Ellipsis:
                continue
        if isinstance(statement, ast.Pass):
            continue
        return False
    return True


def function_source(
    node: ast.FunctionDef | ast.AsyncFunctionDef, source: str
) -> str:
    """Return the source text of a function definition."""
    try:
        return ast.get_source_segment(source, node) or ""
    except Exception:  # noqa: BLE001 - best effort only
        return ""


def metric_literal_nodes(tree: ast.AST) -> list[tuple[int, str]]:
    """Find metric names bound to a hard-coded number.

    Two shapes count: a dictionary entry (`{"accuracy": 0.95}`) and a plain
    assignment (`accuracy = 0.95`). A value that is *computed* — a name, a
    call, an expression — is fine, because that is what a real evaluation run
    produces.
    """
    findings: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant):
                    continue
                if not isinstance(key.value, str):
                    continue
                if key.value.lower() not in METRIC_NAMES:
                    continue
                if isinstance(value, ast.Constant) and isinstance(
                    value.value, (int, float)
                ) and not isinstance(value.value, bool):
                    findings.append(
                        (value.lineno, f"{key.value} = {value.value!r}")
                    )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            value = node.value
            if value is None:
                continue
            if not (
                isinstance(value, ast.Constant)
                and isinstance(value.value, (int, float))
                and not isinstance(value.value, bool)
            ):
                continue
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id.lower() not in METRIC_NAMES:
                    continue
                findings.append((value.lineno, f"{target.id} = {value.value!r}"))

    return findings


def is_ready_ignores_files(
    node: ast.FunctionDef | ast.AsyncFunctionDef, module_source: str
) -> bool:
    """True when an `is_ready()` cannot be telling the truth about the files.

    An `is_ready()` is honest when it either returns a constant `False` (no
    model will ever be claimed) or consults the file system, directly or
    through a helper method defined in the same module.
    """
    body_source = function_source(node, module_source)
    if "return False" in body_source or "return  False" in body_source:
        return False

    if any(marker in body_source for marker in EXISTENCE_MARKERS):
        return False

    # Look one level down: `is_ready()` may delegate to a loader.
    try:
        module_tree = ast.parse(module_source)
    except SyntaxError:
        return True

    for candidate in ast.walk(module_tree):
        if not isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if candidate is node:
            continue
        if candidate.name not in body_source:
            continue
        helper_source = function_source(candidate, module_source)
        if any(marker in helper_source for marker in EXISTENCE_MARKERS):
            return False

    return True


def scan_file(path: Path, report: Report) -> None:
    """Apply every static rule to one Python file."""
    relative = path.relative_to(REPO_ROOT)
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(relative))
    except SyntaxError as exc:
        report.fail(f"{relative} does not parse: {exc}")
        return

    # -- absolute paths ---------------------------------------------------
    absolute_paths: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = ABSOLUTE_PATH_RE.search(node.value)
            if match:
                absolute_paths.append((node.lineno, match.group(0)))
    if absolute_paths:
        for lineno, found in absolute_paths:
            report.fail(
                f"{relative}:{lineno} hard-codes the absolute path {found!r}; "
                "model artefacts must be located relative to the package"
            )
    else:
        report.ok(f"{relative} contains no hard-coded absolute paths")

    # -- predict-like functions returning a literal ------------------------
    literal_returns: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith(PREDICT_LIKE_PREFIXES):
            continue
        if is_abstract(node.body):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Return) or child.value is None:
                continue
            value = child.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, (int, float))
                and not isinstance(value.value, bool)
            ):
                literal_returns.append(
                    (child.lineno, f"{node.name}() returns {value.value!r}")
                )
    if literal_returns:
        for lineno, detail in literal_returns:
            report.fail(
                f"{relative}:{lineno} {detail}; a prediction must be computed, "
                "never hard-coded"
            )
    else:
        report.ok(f"{relative} has no prediction function returning a literal")

    # -- literal metric values ---------------------------------------------
    metrics = metric_literal_nodes(tree)
    if metrics:
        for lineno, detail in metrics:
            report.fail(
                f"{relative}:{lineno} hard-codes the metric {detail}; metrics "
                "must come from a real evaluation run"
            )
    else:
        report.ok(f"{relative} hard-codes no evaluation metric")

    # -- is_ready() that ignores the file system ----------------------------
    dishonest: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "is_ready":
            continue
        if is_abstract(node.body):
            continue
        if is_ready_ignores_files(node, source):
            dishonest.append((node.lineno, node.name))
    if dishonest:
        for lineno, name in dishonest:
            report.fail(
                f"{relative}:{lineno} {name}() does not check whether the "
                "model file exists, so it cannot be telling the truth"
            )
    else:
        report.ok(f"{relative} has no is_ready() that ignores the file system")


def scan_sources(report: Report) -> None:
    """Apply the static rules to every Python file under `ai/`."""
    files = python_files()
    if not files:
        report.fail(f"no Python files found under {AI_DIR}")
        return

    for path in files:
        scan_file(path, report)
    report.ok(f"scanned {len(files)} Python file(s) under {AI_DIR}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run every check and print a PASS/FAIL report."""
    report = Report()

    print("no-model-path / honesty verification")
    print("=" * 60)

    check_registry(report)
    check_model_directory(report)
    scan_sources(report)

    for message in report.passed:
        print(f"PASS  {message}")
    for message in report.failed:
        print(f"FAIL  {message}")
    print("-" * 60)
    print(f"{len(report.passed)} passed, {len(report.failed)} failed")

    if report.failed:
        print("RESULT: FAIL")
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
