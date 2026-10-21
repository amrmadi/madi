"""AI capability endpoints.

What this router does — and deliberately does not do
----------------------------------------------------
It **reports** which AI capabilities exist and whether each one is usable. It
does **not** fabricate predictions: there is no `/ai/fall-detection/predict`
endpoint that returns a made-up answer, because returning a plausible-looking
fall prediction with no model behind it would be dangerous and dishonest.

When Phase 5 produces real trained models, the prediction endpoints get added
here. They will call `ai.registry.get_predictor(...)`, and a predictor that is
not ready raises `ModelNotLoadedError`, which this module converts into an
honest HTTP 503 (`MODEL_NOT_LOADED`).

Access: any signed-in user may read the capability list. It contains no
personal data — only what the system can and cannot do.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ai.base import ModelNotLoadedError
from ai.registry import AVAILABLE_PREDICTORS, get_predictor, list_predictors
from backend.app.core.deps import get_current_user
from backend.app.core.errors import NotFoundError, ServiceUnavailableError
from backend.app.models.identity import User
from backend.app.schemas.ai import PredictorListResponse, PredictorStatus

router = APIRouter(tags=["AI"])


def _capability_check_sample(name: str) -> object:
    """A small, obviously synthetic input used to prove a predictor can run.

    This is **not** a measurement of anybody. It exists only so that the
    `/check` endpoint exercises the real inference path instead of passing a
    placeholder. The predictor marks its output `is_simulated`, so the result
    can never be mistaken for a resident's data.

    For fall detection the sample is plain accelerometer triples in g: a person
    standing still (magnitude ~1 g, gravity only). It is built with a list so
    this module does not need numpy to serve a status endpoint.
    """
    if name == "fall_detection":
        # 500 samples (2.5 s at 200 Hz) of a stationary sensor: (x, y, z) in g.
        return [[0.0, 0.0, 1.0] for _ in range(500)]

    # No other predictor has an input contract yet; an empty vector is enough to
    # demonstrate that the call fails for the honest reason (no model).
    return []


@router.get(
    "/ai/predictors",
    response_model=PredictorListResponse,
    summary="List the AI capabilities and whether each is usable",
    description=(
        "Reports every AI capability this project declares, together with "
        "whether a trained model is actually loaded for it.\n\n"
        "**Today every entry has `is_ready: false`.** No model has been trained "
        "and no dataset has been downloaded, so this endpoint exists to state "
        "that plainly rather than to serve predictions.\n\n"
        "**Access:** any authenticated user."
    ),
)
def list_ai_predictors(_: User = Depends(get_current_user)) -> PredictorListResponse:
    """Describe each predictor and whether it is genuinely usable."""
    described = list_predictors()
    any_ready = any(entry["is_ready"] for entry in described)

    return PredictorListResponse(
        predictors=[PredictorStatus(**entry) for entry in described],
        any_ready=any_ready,
        note=(
            "No AI model is loaded. These endpoints report capability only; "
            "they do not return predictions."
            if not any_ready
            else "At least one trained model is loaded and usable."
        ),
    )


@router.get(
    "/ai/predictors/{name}",
    response_model=PredictorStatus,
    summary="Describe one AI capability",
    description=(
        "Same information as the list endpoint, for a single predictor.\n\n"
        "Returns **404** for an unknown predictor name, so a typo is reported "
        "rather than silently answered with a placeholder.\n\n"
        "**Access:** any authenticated user."
    ),
)
def get_ai_predictor(
    name: str, _: User = Depends(get_current_user)
) -> PredictorStatus:
    """Describe a single predictor, or 404 when the name is unknown."""
    if name not in AVAILABLE_PREDICTORS:
        raise NotFoundError(
            f"No AI predictor named {name!r} is declared by this API.",
            details={"known_predictors": sorted(AVAILABLE_PREDICTORS)},
        )

    predictor = get_predictor(name)
    info = predictor.info

    return PredictorStatus(
        name=name,
        is_ready=predictor.is_ready(),
        model_version=info.version or None,
        trained_at=info.trained_at,
        metrics=info.metrics,
        dataset=info.dataset,
    )


@router.post(
    "/ai/predictors/{name}/check",
    summary="Confirm whether a predictor can run",
    description=(
        "Asks a predictor to actually run and reports the outcome.\n\n"
        "For a predictor with no model this always returns **503** with code "
        "`MODEL_NOT_LOADED`, which makes the 'not available yet' behaviour "
        "verifiable rather than merely documented.\n\n"
        "When a model **is** loaded, this runs it against a small, clearly "
        "synthetic sample and returns the result. That result is flagged "
        "`is_simulated: true`, because a capability check must never look like a "
        "reading taken from a resident.\n\n"
        "**Access:** any authenticated user."
    ),
    responses={
        503: {
            "description": "No trained model is loaded for this predictor.",
        },
        404: {"description": "Unknown predictor name."},
    },
)
def check_ai_predictor(name: str, _: User = Depends(get_current_user)) -> dict:
    """Attempt inference, reporting honestly when no model is loaded."""
    if name not in AVAILABLE_PREDICTORS:
        raise NotFoundError(
            f"No AI predictor named {name!r} is declared by this API.",
            details={"known_predictors": sorted(AVAILABLE_PREDICTORS)},
        )

    predictor = get_predictor(name)
    try:
        result = predictor.predict(features=_capability_check_sample(name))
    except ModelNotLoadedError as exc:
        raise ServiceUnavailableError(
            str(exc),
            code="MODEL_NOT_LOADED",
            details={"predictor": name, "reason": exc.reason},
        ) from exc

    return result.as_dict()
