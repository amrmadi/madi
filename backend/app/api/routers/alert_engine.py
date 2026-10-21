"""Alert-engine and lifecycle endpoints.

These expose the rule engine from `backend/app/services/alert_rules.py` over
HTTP, plus the acknowledgement/resolution transitions.

Two endpoints matter most:

* `POST /elderly-profiles/{id}/alerts/evaluate` — the **explainability**
  endpoint. It runs the rules against an observation and returns the decision
  *with the thresholds that produced it*. By default it persists nothing, so a
  reviewer can ask "what would happen?" safely.
* `POST /alerts/{id}/resolve` and `/dismiss` — complete the alert lifecycle
  started by acknowledge. Dismissal is recorded rather than deleted, because
  false-alarm rate is a KPI.

Nothing here invents a detection. An observation is submitted by a caller (a
sensor pipeline, a test, a human), and the engine only classifies what it is
given.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.app.core.deps import get_accessible_profile, get_current_user
from backend.app.core.errors import ConflictError, NotFoundError
from backend.app.db.base import get_db
from backend.app.models.alerts import Alert
from backend.app.models.enums import AlertStatus
from backend.app.models.identity import ElderlyProfile, User
from backend.app.schemas.alerts_engine import (
    AlertEvaluationResult,
    AlertResolveIn,
    AlertStatusActionOut,
    ObservationIn,
    RuleMatchOut,
)
from backend.app.schemas.events import AlertRead
from backend.app.services import alert_service
from backend.app.services.alert_rules import AlertRuleEngine, Observation, RuleMatch

router = APIRouter(tags=["Alert engine"])


def _to_observation(payload: ObservationIn) -> Observation:
    """Convert the API payload into the engine's pure input type."""
    from backend.app.services.alert_rules import build_dedupe_key

    dedupe_key = build_dedupe_key(
        alert_type=payload.kind.value,
        elderly_profile_id=payload.elderly_profile_id,
        observed_at=payload.observed_at,
        source_event_id=payload.source_event_id,
    )
    return Observation(
        kind=payload.kind,
        elderly_profile_id=payload.elderly_profile_id,
        observed_at=payload.observed_at,
        values=dict(payload.values),
        dedupe_key=dedupe_key,
        verified=payload.verified,
        source_event_type=payload.source_event_type,
        source_event_id=payload.source_event_id,
    )


def _to_match_out(match: RuleMatch) -> RuleMatchOut:
    """Serialise a rule match, keeping the reasoning fields."""
    return RuleMatchOut(
        outcome=match.outcome.value,
        alert_type=match.alert_type,
        priority=match.priority.value,
        title=match.title,
        message=match.message,
        dedupe_key=match.dedupe_key,
        rule_name=match.rule_name,
        applied_thresholds=match.applied_thresholds,
        triggered_by_missing_data=match.triggered_by_missing_data,
        should_alert=match.should_alert,
    )


@router.post(
    "/elderly-profiles/{profile_id}/alerts/evaluate",
    response_model=AlertEvaluationResult,
    status_code=status.HTTP_200_OK,
    summary="Evaluate an observation against the alert rules",
    description=(
        "Runs the configurable rule engine on one observation and returns the "
        "decision **and the thresholds that produced it**.\n\n"
        "By default this only *explains*: no alert is created. Set `persist` to "
        "`true` to create or bump an alert.\n\n"
        "Two rules matter here:\n"
        "* a missing value (for example a fall with no confidence) never "
        "produces an emergency;\n"
        "* `priority` is **operational triage**, not validated medical risk.\n\n"
        "**Access:** the caller must be assigned to the resident."
    ),
    responses={403: {"description": "You are not assigned to this resident."}},
)
def evaluate_observation(
    profile_id: int,
    payload: ObservationIn,
    persist: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertEvaluationResult:
    """Evaluate (and optionally persist) one observation."""
    profile = get_accessible_profile(profile_id, db, current_user)

    # The path id is authoritative; trusting the body would let a caller probe
    # another resident's rules by mismatching the two.
    body = payload.model_copy(update={"elderly_profile_id": profile.id})
    observation = _to_observation(body)

    engine = AlertRuleEngine()
    match = engine.evaluate(observation)

    alert_id: int | None = None
    if persist and match.should_alert:
        persisted = alert_service.apply_match(db, match, observation)
        alert_id = persisted.id if persisted is not None else None

    return AlertEvaluationResult(
        observation=body,
        match=_to_match_out(match),
        persisted_alert_id=alert_id,
        persisted=alert_id is not None,
    )


def _get_alert_or_404(alert_id: int, db: Session, current_user: User) -> Alert:
    """Load an alert and verify the caller may see its resident."""
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(
            f"Alert with id {alert_id} does not exist.", code="ALERT_NOT_FOUND"
        )
    get_accessible_profile(alert.elderly_profile_id, db, current_user)
    return alert


def _to_action_out(alert: Alert) -> AlertStatusActionOut:
    """Shape the response for a lifecycle transition."""
    return AlertStatusActionOut(
        id=alert.id,
        status=alert.status,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by_user_id=alert.acknowledged_by_user_id,
        resolved_at=alert.resolved_at,
        occurrence_count=alert.occurrence_count,
    )


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=AlertStatusActionOut,
    summary="Resolve an alert",
    description=(
        "Marks an alert as resolved, recording who resolved it and when. If it "
        "had not been acknowledged yet, it is acknowledged as part of resolving, "
        "because a resolved alert was by definition seen."
    ),
    responses={
        403: {"description": "You are not assigned to this resident."},
        409: {"description": "The alert is already dismissed."},
    },
)
def resolve_alert(
    alert_id: int,
    payload: AlertResolveIn | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertStatusActionOut:
    """Resolve an alert."""
    alert = _get_alert_or_404(alert_id, db, current_user)

    if alert.status == AlertStatus.DISMISSED.value:
        raise ConflictError(
            "A dismissed alert cannot be resolved. It was already judged not to "
            "need action.",
            code="ALERT_ALREADY_DISMISSED",
        )

    alert_service.resolve_alert(
        db, alert, user_id=current_user.id, note=payload.note if payload else None
    )
    return _to_action_out(alert)


@router.post(
    "/alerts/{alert_id}/dismiss",
    response_model=AlertStatusActionOut,
    summary="Dismiss an alert",
    description=(
        "Records that a human judged the alert to need no action (a false alarm "
        "or something already handled). The row is kept, not deleted, so "
        "false-alarm rate can be measured later."
    ),
    responses={
        403: {"description": "You are not assigned to this resident."},
        409: {"description": "The alert is already resolved."},
    },
)
def dismiss_alert(
    alert_id: int,
    payload: AlertResolveIn | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertStatusActionOut:
    """Dismiss an alert as requiring no action."""
    alert = _get_alert_or_404(alert_id, db, current_user)

    if alert.status == AlertStatus.RESOLVED.value:
        raise ConflictError(
            "A resolved alert cannot be dismissed.",
            code="ALERT_ALREADY_RESOLVED",
        )

    alert_service.dismiss_alert(
        db, alert, user_id=current_user.id, note=payload.note if payload else None
    )
    return _to_action_out(alert)


@router.get(
    "/alert-rules",
    summary="Describe the configured alert rules",
    description=(
        "Returns the thresholds the rule engine is currently using, so the "
        "behaviour of the engine is inspectable rather than hidden in code. "
        "Available to any signed-in user; it contains no personal data."
    ),
)
def describe_rules(current_user: User = Depends(get_current_user)) -> dict[str, object]:
    """Expose the active rule configuration and the caps that protect safety."""
    config = AlertRuleEngine().config
    return {
        "explanation": (
            "Priority is operational triage (how urgently a person should look), "
            "not validated medical risk. Missing data alone never produces an "
            "emergency."
        ),
        "fall": {
            "min_confidence_to_alert": config.fall_min_confidence,
            "report_floor": config.fall_report_floor,
            "verified_priority": config.fall_verified_priority.value,
            "unverified_priority_cap": "high",
        },
        "data_gap": {
            "mention_after_seconds": int(config.data_gap_mention_after.total_seconds()),
            "max_priority": config.data_gap_max_priority.value,
            "note": "A data gap can never exceed this priority, however long it lasts.",
        },
        "missed_checkin": {
            "grace_period_seconds": int(config.checkin_grace_period.total_seconds()),
            "priority": config.missed_checkin_priority.value,
            "repeat_priority": config.missed_checkin_repeat_priority.value,
        },
        "missed_medication": {
            "priority": config.missed_medication_priority.value,
            "repeat_priority": config.missed_medication_repeat_priority.value,
        },
        "anomaly": {
            "min_score": config.anomaly_min_score,
            "high_score": config.anomaly_high_score,
            "max_priority": config.anomaly_max_priority.value,
        },
        "risk": {
            "high_score": config.risk_high_score,
            "priority": config.risk_priority.value,
            "high_priority": config.risk_high_priority.value,
            "note": "Only a verified assessment can reach high priority.",
        },
        "deduplication": {
            "default_cooldown_seconds": int(config.default_cooldown.total_seconds()),
            "fall_cooldown_seconds": int(config.fall_cooldown.total_seconds()),
        },
    }


@router.get(
    "/alerts/{alert_id}/timeline",
    response_model=AlertRead,
    summary="Read one alert with its lifecycle timestamps",
    description=(
        "Returns the alert with `created_at`, `acknowledged_at`, and "
        "`resolved_at` so the time from raise to acknowledge to resolve is "
        "visible. These are the timestamps the acknowledgement KPI is built from."
    ),
)
def alert_timeline(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertRead:
    """Return one alert including its lifecycle timestamps."""
    alert = _get_alert_or_404(alert_id, db, current_user)
    profile = db.get(ElderlyProfile, alert.elderly_profile_id)
    result = AlertRead.model_validate(alert)
    result.elderly_profile_name = profile.display_name if profile else None
    return result
