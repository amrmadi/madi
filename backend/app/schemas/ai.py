"""Response schemas for the AI endpoints.

These exist to make the API's honesty visible in the generated OpenAPI docs: a
machine reading `/docs` should see that `is_ready` can be false and that
`metrics` may legitimately be `None`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PredictorStatus(BaseModel):
    """Whether one AI capability is actually usable right now."""

    name: str = Field(
        description="Stable identifier, e.g. `fall_detection`.",
    )
    is_ready: bool = Field(
        description=(
            "True only when a trained model is loaded and can be used. This "
            "depends on the model file being present on the machine running the "
            "API, so it may legitimately be false even where a model has been "
            "trained."
        ),
    )
    model_version: str | None = Field(
        default=None,
        description="Version of the loaded model, or null when none is loaded.",
    )
    trained_at: str | None = Field(
        default=None,
        description="When the model was trained, or null when none is loaded.",
    )
    metrics: dict[str, float] | None = Field(
        default=None,
        description=(
            "Evaluation metrics **as actually measured**, or null. Never "
            "populated with placeholder numbers."
        ),
    )
    dataset: str | None = Field(
        default=None,
        description="The public dataset this model will be trained on.",
    )


class PredictorListResponse(BaseModel):
    """Every AI capability this API declares, and whether it works yet."""

    predictors: list[PredictorStatus]
    any_ready: bool = Field(
        description="Convenience flag: true when at least one model is loaded.",
    )
    note: str = Field(
        description="Plain-language statement of the current AI status.",
    )
