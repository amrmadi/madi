"""Endpoints for activity events and alerts.

Honesty guarantees built into this module:

* Activity events default to `source = "simulated"`. Demo or seeded data can
  therefore never be mistaken for real sensor readings.
* Recorded activity is described as *recorded*, not as a model prediction —
  linking events to AI inference happens in Phase 6 via `model_run_id`, and the
  API only reports what is actually stored.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.deps import (
    accessible_profile_ids,
    get_current_user,
    get_accessible_profile,
    is_admin,
)
from backend.app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from backend.app.db.base import get_db
from backend.app.models.enums import AlertStatus, UserRole
from backend.app.models.events import ActivityEvent
from backend.app.models.alerts import Alert
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User
from backend.app.schemas.events import (
    ActivityEventCreate,
    ActivityEventRead,
    AlertAcknowledge,
    AlertCreate,
    AlertRead,
    AlertUpdate,
)
from backend.app.schemas.responses import Paginated

router = APIRouter(tags=["Activity events & alerts"])


def _enum_value(value):
    """Return the stored string for an enum member, or the value unchanged."""
    return value.value if hasattr(value, "value") else value


# ---------------------------------------------------------------------------
# Activity events
# ---------------------------------------------------------------------------


@router.get(
    "/elderly-profiles/{profile_id}/activity-events",
    response_model=Paginated[ActivityEventRead],
    summary="List a resident's activity history",
    description=(
        "Returns recorded activity events, newest first. Optional `start`/`end` "
        "filters narrow the time window.\n\n"
        "**Access:** the caller must be assigned to the resident."
    ),
    responses={403: {"description": "You are not assigned to this resident."}},
)
def list_activity_events(
    profile_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    start: datetime | None = Query(
        None, description="Only events starting at or after this time (ISO 8601)."
    ),
    end: datetime | None = Query(
        None, description="Only events starting before this time (ISO 8601)."
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Paginated[ActivityEventRead]:
    """Return a page of activity events for a resident, enforcing access.

    The query parameters are named `start`/`end` rather than `from`/`to`.
    `from` is a reserved word in Python, and aliasing it produced a 422 from
    FastAPI's query validation; clearer names also read better in the API docs.
    """
    get_accessible_profile(profile_id, db, current_user)

    filters = [ActivityEvent.elderly_profile_id == profile_id]
    if start is not None:
        filters.append(ActivityEvent.started_at >= start)
    if end is not None:
        filters.append(ActivityEvent.started_at < end)

    total = db.execute(
        select(func.count()).select_from(ActivityEvent).where(*filters)
    ).scalar_one()
    rows = (
        db.execute(
            select(ActivityEvent)
            .where(*filters)
            .order_by(ActivityEvent.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return Paginated[ActivityEventRead](
        items=[ActivityEventRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/elderly-profiles/{profile_id}/activity-events",
    response_model=ActivityEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record an activity event",
    description=(
        "Records an activity observation.\n\n"
        "`source` defaults to **`simulated`**, so data entered for a demo or "
        "test is never presented as a real sensor measurement. Use `sensor` "
        "only for genuine device data, or `model` when a model produced it."
    ),
)
def create_activity_event(
    profile_id: int,
    payload: ActivityEventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActivityEvent:
    """Record an activity event for a resident."""
    profile = get_accessible_profile(profile_id, db, current_user)

    event = ActivityEvent(
        elderly_profile_id=profile.id,
        activity_type=_enum_value(payload.activity_type),
        confidence=payload.confidence,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        duration_seconds=payload.duration_seconds,
        source=_enum_value(payload.source),
        room_label=payload.room_label,
        note=payload.note,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def _to_alert_read(alert: Alert, profile_name: str | None) -> AlertRead:
    """Convert an alert row to its API shape, adding the resident's name."""
    result = AlertRead.model_validate(alert)
    result.elderly_profile_name = profile_name
    return result


@router.get(
    "/alerts",
    response_model=Paginated[AlertRead],
    summary="List alerts you can see",
    description=(
        "Returns alerts across every resident the caller is assigned to.\n\n"
        "**Access:** a caregiver sees alerts only for their own residents; "
        "administrators see all alerts."
    ),
)
def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: AlertStatus | None = Query(
        None, alias="status", description="Filter by alert status."
    ),
    severity: str | None = Query(None, description="Filter by severity level."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Paginated[AlertRead]:
    """List alerts within the caller's access scope."""
    query = select(Alert, ElderlyProfile.display_name).join(
        ElderlyProfile, ElderlyProfile.id == Alert.elderly_profile_id
    )
    count_query = select(func.count()).select_from(Alert)

    scope = accessible_profile_ids(db, current_user)
    if scope is not None:
        if not scope:
            return Paginated[AlertRead](items=[], total=0, page=page, page_size=page_size)
        query = query.where(Alert.elderly_profile_id.in_(scope))
        count_query = count_query.where(Alert.elderly_profile_id.in_(scope))

    if status_filter is not None:
        value = _enum_value(status_filter)
        query = query.where(Alert.status == value)
        count_query = count_query.where(Alert.status == value)

    if severity is not None:
        query = query.where(Alert.severity == severity)
        count_query = count_query.where(Alert.severity == severity)

    total = db.execute(count_query).scalar_one()
    rows = db.execute(
        query.order_by(Alert.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    return Paginated[AlertRead](
        items=[_to_alert_read(alert, name) for alert, name in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/elderly-profiles/{profile_id}/alerts",
    response_model=Paginated[AlertRead],
    summary="List a resident's alerts",
)
def list_profile_alerts(
    profile_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Paginated[AlertRead]:
    """Return alerts for one resident the caller may access."""
    profile = get_accessible_profile(profile_id, db, current_user)

    total = db.execute(
        select(func.count()).select_from(Alert).where(Alert.elderly_profile_id == profile.id)
    ).scalar_one()
    rows = (
        db.execute(
            select(Alert)
            .where(Alert.elderly_profile_id == profile.id)
            .order_by(Alert.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return Paginated[AlertRead](
        items=[_to_alert_read(a, profile.display_name) for a in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/elderly-profiles/{profile_id}/alerts",
    response_model=AlertRead,
    status_code=status.HTTP_201_CREATED,
    summary="Raise an alert manually",
    description=(
        "Records an alert by hand (for example a caregiver noticing something "
        "concerning). Automatic alerts from the monitoring pipeline arrive in "
        "Phase 5."
    ),
)
def create_alert(
    profile_id: int,
    payload: AlertCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertRead:
    """Create an alert for a resident."""
    profile = get_accessible_profile(profile_id, db, current_user)

    alert = Alert(
        elderly_profile_id=profile.id,
        alert_type=_enum_value(payload.alert_type),
        severity=_enum_value(payload.severity),
        status=AlertStatus.NEW.value,
        title=payload.title,
        message=payload.message,
        occurrence_count=1,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _to_alert_read(alert, profile.display_name)


def _get_alert_or_404(alert_id: int, db: Session, current_user: User) -> Alert:
    """Load an alert and verify the caller may see its resident."""
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(
            f"Alert with id {alert_id} does not exist.", code="ALERT_NOT_FOUND"
        )
    get_accessible_profile(alert.elderly_profile_id, db, current_user)
    return alert


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertRead,
    summary="Read one alert",
)
def read_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertRead:
    """Return a single alert."""
    alert = _get_alert_or_404(alert_id, db, current_user)
    profile = db.get(ElderlyProfile, alert.elderly_profile_id)
    return _to_alert_read(alert, profile.display_name if profile else None)


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertRead,
    summary="Update an alert",
    description="Typically used to change `status`.",
)
def update_alert(
    alert_id: int,
    payload: AlertUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertRead:
    """Update an alert's status or message."""
    alert = _get_alert_or_404(alert_id, db, current_user)

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(alert, field, _enum_value(value))

    # Keep the acknowledgement timestamp consistent with the status, and record
    # who acknowledged it — the audit trail matters for care records.
    if "status" in changes:
        new_status = alert.status
        if new_status == AlertStatus.ACKNOWLEDGED.value:
            alert.acknowledged_at = alert.acknowledged_at or datetime.now(timezone.utc)
            alert.acknowledged_by_user_id = alert.acknowledged_by_user_id or current_user.id
        elif new_status == AlertStatus.RESOLVED.value:
            alert.acknowledged_at = alert.acknowledged_at or datetime.now(timezone.utc)
            alert.acknowledged_by_user_id = alert.acknowledged_by_user_id or current_user.id
            alert.resolved_at = alert.resolved_at or datetime.now(timezone.utc)
        elif new_status == AlertStatus.NEW.value:
            alert.acknowledged_at = None
            alert.acknowledged_by_user_id = None
            alert.resolved_at = None

    db.commit()
    db.refresh(alert)
    profile = db.get(ElderlyProfile, alert.elderly_profile_id)
    return _to_alert_read(alert, profile.display_name if profile else None)


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertRead,
    summary="Acknowledge an alert",
    description=(
        "Marks an alert as seen by a caregiver and records **who** acknowledged "
        "it and when."
    ),
    responses={409: {"description": "The alert was already acknowledged."}},
)
def acknowledge_alert(
    alert_id: int,
    payload: AlertAcknowledge | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertRead:
    """Acknowledge an alert on behalf of the signed-in caregiver."""
    alert = _get_alert_or_404(alert_id, db, current_user)

    if alert.status in (AlertStatus.RESOLVED.value, AlertStatus.DISMISSED.value):
        from backend.app.core.errors import ConflictError

        raise ConflictError(
            f"This alert is already {alert.status} and cannot be acknowledged again.",
            code="ALERT_ALREADY_CLOSED",
        )

    alert.status = AlertStatus.ACKNOWLEDGED.value
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by_user_id = current_user.id
    if payload is not None and payload.note:
        # Append the note to the message rather than overwriting the original
        # alert text, so the original reason for the alert is preserved.
        alert.message = f"{alert.message or ''}\n\nAcknowledgement note: {payload.note}".strip()

    db.commit()
    db.refresh(alert)
    profile = db.get(ElderlyProfile, alert.elderly_profile_id)
    return _to_alert_read(alert, profile.display_name if profile else None)
