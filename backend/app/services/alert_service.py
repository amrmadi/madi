"""Persist rule-engine decisions as alerts, with deduplication and lifecycle.

This is the impure layer: it touches the database. The *decision* itself stays
in `alert_rules.py` (pure); this module only executes that decision.

Deduplication contract
----------------------
When an observation resolves to a rule match whose `dedupe_key` matches an
existing alert that is still inside its cooldown window, we do **not** create a
second alert. Instead we bump `occurrence_count` and refresh nothing else, so
the caregiver sees "the same problem, 4 times" rather than four separate pages.

A repeat after the cooldown creates a genuinely new alert, because a problem
that recurs an hour later is new information.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.alerts import Alert
from backend.app.models.enums import AlertStatus
from backend.app.services.alert_rules import (
    AlertRuleEngine,
    Observation,
    RuleMatch,
    RuleOutcome,
    is_within_cooldown,
    next_occurrence_count,
)


def _as_utc(moment: datetime) -> datetime:
    """Normalise a possibly-naive datetime to UTC-aware."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _find_open_duplicate(
    db: Session, *, elderly_profile_id: int, dedupe_key: str
) -> Alert | None:
    """Find an unresolved alert with the same dedupe key, newest first."""
    return (
        db.execute(
            select(Alert)
            .where(
                Alert.elderly_profile_id == elderly_profile_id,
                Alert.dedupe_key == dedupe_key,
                Alert.status.in_((AlertStatus.NEW.value, AlertStatus.ACKNOWLEDGED.value)),
            )
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def apply_match(
    db: Session,
    match: RuleMatch,
    observation: Observation,
    *,
    now: datetime | None = None,
) -> Alert | None:
    """Persist a rule match, deduplicating against an existing open alert.

    Returns the created or bumped `Alert`, or None when the engine decided not
    to alert (in which case nothing is written — no silent placeholder rows).
    """
    if not match.should_alert:
        return None

    moment = _as_utc(now or datetime.now(timezone.utc))
    engine_config = AlertRuleEngine().config
    cooldown = engine_config.cooldown_for(match.alert_type or "")

    existing = None
    if match.dedupe_key:
        candidate = _find_open_duplicate(
            db,
            elderly_profile_id=observation.elderly_profile_id,
            dedupe_key=match.dedupe_key,
        )
        if candidate is not None and is_within_cooldown(
            existing_created_at=_as_utc(candidate.created_at),
            now=moment,
            window=cooldown,
        ):
            existing = candidate

    if existing is not None:
        # Same problem, still fresh: bump the counter, keep the original text so
        # the first, most informative message is not lost.
        existing.occurrence_count = next_occurrence_count(existing.occurrence_count)
        db.commit()
        db.refresh(existing)
        return existing

    alert = Alert(
        elderly_profile_id=observation.elderly_profile_id,
        alert_type=match.alert_type,
        severity=match.priority.value,
        status=AlertStatus.NEW.value,
        title=match.title,
        message=match.message,
        source_event_type=observation.source_event_type,
        source_event_id=observation.source_event_id,
        dedupe_key=match.dedupe_key,
        occurrence_count=1,
        created_at=moment,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def evaluate_and_apply(
    db: Session,
    observation: Observation,
    *,
    engine: AlertRuleEngine | None = None,
    now: datetime | None = None,
) -> tuple[RuleMatch, Alert | None]:
    """Evaluate an observation and persist it, returning the decision + alert."""
    active_engine = engine or AlertRuleEngine()
    match = active_engine.evaluate(observation)
    alert = apply_match(db, match, observation, now=now)
    return match, alert


def acknowledge_alert(
    db: Session,
    alert: Alert,
    *,
    user_id: int,
    note: str | None = None,
    now: datetime | None = None,
) -> Alert:
    """Acknowledge an alert, recording who and when.

    Keeps the original message and appends the note, so the reason the alert was
    raised survives.
    """
    moment = _as_utc(now or datetime.now(timezone.utc))
    alert.status = AlertStatus.ACKNOWLEDGED.value
    alert.acknowledged_at = alert.acknowledged_at or moment
    alert.acknowledged_by_user_id = alert.acknowledged_by_user_id or user_id
    if note:
        alert.message = (
            f"{alert.message or ''}\n\nAcknowledgement note: {note}".strip()
        )
    db.commit()
    db.refresh(alert)
    return alert


def resolve_alert(
    db: Session,
    alert: Alert,
    *,
    user_id: int,
    note: str | None = None,
    now: datetime | None = None,
) -> Alert:
    """Resolve an alert: acknowledged (if it was not) and closed."""
    moment = _as_utc(now or datetime.now(timezone.utc))
    if alert.acknowledged_at is None:
        alert.acknowledged_at = moment
    if alert.acknowledged_by_user_id is None:
        alert.acknowledged_by_user_id = user_id
    alert.status = AlertStatus.RESOLVED.value
    alert.resolved_at = alert.resolved_at or moment
    if note:
        alert.message = f"{alert.message or ''}\n\nResolution note: {note}".strip()
    db.commit()
    db.refresh(alert)
    return alert


def dismiss_alert(
    db: Session,
    alert: Alert,
    *,
    user_id: int,
    note: str | None = None,
    now: datetime | None = None,
) -> Alert:
    """Dismiss an alert as not requiring action.

    Dismissed means "a human judged this a false alarm or irrelevant". It is
    recorded rather than deleted, because false-alarm rate is a KPI we care
    about.
    """
    moment = _as_utc(now or datetime.now(timezone.utc))
    alert.status = AlertStatus.DISMISSED.value
    alert.acknowledged_at = alert.acknowledged_at or moment
    alert.acknowledged_by_user_id = alert.acknowledged_by_user_id or user_id
    if note:
        alert.message = f"{alert.message or ''}\n\nDismissal note: {note}".strip()
    db.commit()
    db.refresh(alert)
    return alert


LIFECYCLE_ACTIONS = {
    "acknowledge": acknowledge_alert,
    "resolve": resolve_alert,
    "dismiss": dismiss_alert,
}

__all__ = [
    "LIFECYCLE_ACTIONS",
    "acknowledge_alert",
    "apply_match",
    "dismiss_alert",
    "evaluate_and_apply",
    "resolve_alert",
]
