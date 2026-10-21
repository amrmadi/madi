"""Typed shapes for the alert rule engine and the alert-lifecycle endpoints.

Kept apart from `schemas/events.py` because these describe *engine* inputs and
outputs (observations, decisions, explanations) rather than stored rows.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import AlertType, SeverityLevel


class ObservationKind(str, Enum):
    """The kinds of observation the rule engine knows how to judge.

    The engine ignores any kind it has no rule for (recorded explicitly as
    `suppressed_no_rule`) rather than guessing.
    """

    FALL = "fall"
    DATA_GAP = "data_gap"
    MISSED_CHECKIN = "missed_checkin"
    MISSED_MEDICATION = "missed_medication"
    ANOMALY = "anomaly"
    RISK = "risk"


class ObservationIn(BaseModel):
    """One observation submitted to the rules engine.

    `values` is free-form so each rule can read what it needs (confidence,
    score, minutes_late, ...) without a schema change per rule. Missing keys are
    treated as *missing data*, never as zero.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ObservationKind
    elderly_profile_id: int = Field(ge=1)
    observed_at: datetime
    values: dict[str, float | int | str | None] = Field(default_factory=dict)
    verified: bool = False
    source_event_type: str | None = Field(
        default=None,
        description="One of fall_events, anomaly_events, risk_events, checkins, medication_dose_logs.",
    )
    source_event_id: int | None = None


class RuleMatchOut(BaseModel):
    """The engine's decision plus the thresholds it applied — the explanation."""

    outcome: str
    alert_type: str | None
    priority: str
    title: str
    message: str
    dedupe_key: str | None
    rule_name: str
    applied_thresholds: dict[str, object] = Field(default_factory=dict)
    triggered_by_missing_data: bool
    should_alert: bool


class ObservationEvaluationOut(BaseModel):
    """A single evaluation showing the observation alongside the decision."""

    observation: ObservationIn
    match: RuleMatchOut
    would_persist_alert: bool


class AlertEvaluationResult(BaseModel):
    """Response for evaluating an observation, with optional persistence.

    `persisted_alert_id` is null when the engine decided not to alert, or when
    the caller asked for explanation only (`persist=false`).
    """

    observation: ObservationIn
    match: RuleMatchOut
    persisted_alert_id: int | None = None
    persisted: bool = False


class AlertEvaluateIn(ObservationIn):
    """Evaluate an observation and, optionally, persist the resulting alert."""

    persist: bool = Field(
        default=False,
        description=(
            "When false (default), the engine only explains its decision. Set "
            "true to actually create or bump an alert."
        ),
    )


class AlertResolveIn(BaseModel):
    """Body for resolving an alert."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class AlertStatusActionOut(BaseModel):
    """Result of an acknowledge/resolve transition."""

    id: int
    status: str
    acknowledged_at: datetime | None
    acknowledged_by_user_id: int | None
    resolved_at: datetime | None
    occurrence_count: int


__all__ = [
    "AlertEvaluateIn",
    "AlertEvaluationResult",
    "AlertResolveIn",
    "AlertStatusActionOut",
    "AlertType",
    "ObservationEvaluationOut",
    "ObservationIn",
    "ObservationKind",
    "RuleMatchOut",
    "SeverityLevel",
]
