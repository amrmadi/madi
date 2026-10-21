"""Endpoints for care plans, medications, reminders, and check-ins.

Every route here is scoped to a resident and therefore depends on
`require_profile_access`, which enforces the caregiver assignment rule.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.deps import get_current_user, require_profile_access
from backend.app.core.errors import NotFoundError
from backend.app.db.base import get_db
from backend.app.models.care import (
    CarePlan,
    Checkin,
    CheckinSchedule,
    MedicationSchedule,
    Reminder,
)
from backend.app.models.identity import ElderlyProfile, User
from backend.app.schemas.care import (
    CarePlanCreate,
    CarePlanRead,
    CarePlanUpdate,
    CheckinCreate,
    CheckinRead,
    CheckinScheduleCreate,
    MedicationScheduleCreate,
    MedicationScheduleRead,
    ReminderCreate,
    ReminderRead,
)
from backend.app.schemas.common import Message
from backend.app.schemas.responses import Paginated

router = APIRouter(tags=["Care plans, medications, reminders & check-ins"])


def _enum_value(value):
    """Return the stored string for an enum member, or the value unchanged."""
    return value.value if hasattr(value, "value") else value


# ---------------------------------------------------------------------------
# Care plans
# ---------------------------------------------------------------------------


@router.get(
    "/elderly-profiles/{profile_id}/care-plans",
    response_model=Paginated[CarePlanRead],
    summary="List a resident's care plans",
)
def list_care_plans(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> Paginated[CarePlanRead]:
    """Return a page of care plans for one resident."""
    base = select(CarePlan).where(CarePlan.elderly_profile_id == profile.id)
    total = db.execute(
        select(func.count()).select_from(CarePlan).where(CarePlan.elderly_profile_id == profile.id)
    ).scalar_one()
    rows = (
        db.execute(
            base.order_by(CarePlan.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return Paginated[CarePlanRead](
        items=[CarePlanRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/elderly-profiles/{profile_id}/care-plans",
    response_model=CarePlanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a care plan",
)
def create_care_plan(
    payload: CarePlanCreate,
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CarePlan:
    """Create a care plan for a resident."""
    plan = CarePlan(
        elderly_profile_id=profile.id,
        created_by_user_id=current_user.id,
        title=payload.title,
        summary=payload.summary,
        status=_enum_value(payload.status),
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def _get_plan_or_404(plan_id: int, db: Session) -> CarePlan:
    plan = db.get(CarePlan, plan_id)
    if plan is None:
        raise NotFoundError(
            f"Care plan with id {plan_id} does not exist.", code="CARE_PLAN_NOT_FOUND"
        )
    return plan


@router.get(
    "/care-plans/{plan_id}",
    response_model=CarePlanRead,
    summary="Read one care plan",
)
def read_care_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CarePlan:
    """Return a single care plan, after checking the caller may see its resident."""
    plan = _get_plan_or_404(plan_id, db)
    # Reuse the profile access rule by resolving the plan's resident.
    from backend.app.core.deps import get_accessible_profile

    get_accessible_profile(plan.elderly_profile_id, db, current_user)
    return plan


@router.patch(
    "/care-plans/{plan_id}",
    response_model=CarePlanRead,
    summary="Update a care plan",
)
def update_care_plan(
    plan_id: int,
    payload: CarePlanUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CarePlan:
    """Apply a partial update to a care plan."""
    plan = _get_plan_or_404(plan_id, db)
    from backend.app.core.deps import get_accessible_profile

    get_accessible_profile(plan.elderly_profile_id, db, current_user)

    changes = payload.model_dump(exclude_unset=True)

    # Validate the combined dates, since one side may already be stored.
    start = changes.get("start_date", plan.start_date)
    end = changes.get("end_date", plan.end_date)
    if start and end and end < start:
        from backend.app.core.errors import ValidationError

        raise ValidationError("end_date cannot be earlier than start_date.")

    for field, value in changes.items():
        setattr(plan, field, _enum_value(value))

    db.commit()
    db.refresh(plan)
    return plan


@router.delete(
    "/care-plans/{plan_id}",
    response_model=Message,
    summary="Delete a care plan",
    description="Deletes the plan and its items. Requires access to the resident.",
)
def delete_care_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    """Delete a care plan."""
    plan = _get_plan_or_404(plan_id, db)
    from backend.app.core.deps import get_accessible_profile

    get_accessible_profile(plan.elderly_profile_id, db, current_user)

    db.delete(plan)
    db.commit()
    return Message(detail=f"Care plan {plan_id} deleted.")


# ---------------------------------------------------------------------------
# Medication schedules
# ---------------------------------------------------------------------------


@router.get(
    "/elderly-profiles/{profile_id}/medications",
    response_model=list[MedicationScheduleRead],
    summary="List a resident's medication schedules",
)
def list_medications(
    include_inactive: bool = Query(False),
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> list[MedicationSchedule]:
    """Return medication schedules for one resident."""
    query = select(MedicationSchedule).where(
        MedicationSchedule.elderly_profile_id == profile.id
    )
    if not include_inactive:
        query = query.where(MedicationSchedule.is_active.is_(True))
    return list(
        db.execute(query.order_by(MedicationSchedule.medication_name)).scalars().all()
    )


@router.post(
    "/elderly-profiles/{profile_id}/medications",
    response_model=MedicationScheduleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a medication schedule",
    description=(
        "Records **what should be taken and when**. It does not give medical "
        "advice; dosages are free text entered by a caregiver."
    ),
)
def create_medication(
    payload: MedicationScheduleCreate,
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> MedicationSchedule:
    """Create a medication schedule for a resident."""
    medication = MedicationSchedule(
        elderly_profile_id=profile.id,
        medication_name=payload.medication_name,
        dosage_text=payload.dosage_text,
        instructions=payload.instructions,
        recurrence=_enum_value(payload.recurrence),
        time_of_day=payload.time_of_day,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_active=payload.is_active,
    )
    db.add(medication)
    db.commit()
    db.refresh(medication)
    return medication


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


@router.get(
    "/elderly-profiles/{profile_id}/reminders",
    response_model=list[ReminderRead],
    summary="List a resident's reminders",
)
def list_reminders(
    include_inactive: bool = Query(False),
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> list[Reminder]:
    """Return reminders for one resident."""
    query = select(Reminder).where(Reminder.elderly_profile_id == profile.id)
    if not include_inactive:
        query = query.where(Reminder.is_active.is_(True))
    return list(db.execute(query.order_by(Reminder.time_of_day)).scalars().all())


@router.post(
    "/elderly-profiles/{profile_id}/reminders",
    response_model=ReminderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reminder",
    description=(
        "Creates a repeating reminder such as hydration or a walk.\n\n"
        "A `weekly` reminder must include `day_of_week` (1 = Monday ... 7 = Sunday)."
    ),
)
def create_reminder(
    payload: ReminderCreate,
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> Reminder:
    """Create a reminder for a resident."""
    reminder = Reminder(
        elderly_profile_id=profile.id,
        title=payload.title,
        message=payload.message,
        recurrence=_enum_value(payload.recurrence),
        time_of_day=payload.time_of_day,
        day_of_week=payload.day_of_week,
        is_active=payload.is_active,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------


@router.get(
    "/elderly-profiles/{profile_id}/checkins",
    response_model=Paginated[CheckinRead],
    summary="List a resident's check-ins",
)
def list_checkins(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> Paginated[CheckinRead]:
    """Return a page of check-ins for one resident, newest first."""
    total = db.execute(
        select(func.count()).select_from(Checkin).where(Checkin.elderly_profile_id == profile.id)
    ).scalar_one()
    rows = (
        db.execute(
            select(Checkin)
            .where(Checkin.elderly_profile_id == profile.id)
            .order_by(Checkin.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return Paginated[CheckinRead](
        items=[CheckinRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/elderly-profiles/{profile_id}/checkins",
    response_model=CheckinRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a check-in",
    description=(
        "Records an actual wellbeing or safety check-in. `wellbeing_note` is "
        "free text rather than a clinical score — the system does not diagnose."
    ),
)
def create_checkin(
    payload: CheckinCreate,
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Checkin:
    """Record a check-in for a resident."""
    if payload.checkin_schedule_id is not None:
        schedule = db.get(CheckinSchedule, payload.checkin_schedule_id)
        if schedule is None:
            raise NotFoundError(
                f"Check-in schedule with id {payload.checkin_schedule_id} does not exist.",
                code="CHECKIN_SCHEDULE_NOT_FOUND",
            )
        if schedule.elderly_profile_id != profile.id:
            from backend.app.core.errors import ValidationError

            raise ValidationError(
                "That check-in schedule belongs to a different resident."
            )

    performed = payload.performed_at
    if payload.status.value == "taken" and performed is None:
        # Default a completed check-in to "now" so the history is meaningful.
        performed = datetime.now(timezone.utc)

    checkin = Checkin(
        elderly_profile_id=profile.id,
        checkin_schedule_id=payload.checkin_schedule_id,
        checkin_type=_enum_value(payload.checkin_type),
        status=_enum_value(payload.status),
        scheduled_for=payload.scheduled_for,
        performed_at=performed,
        wellbeing_note=payload.wellbeing_note,
        recorded_by_user_id=current_user.id,
    )
    db.add(checkin)
    db.commit()
    db.refresh(checkin)
    return checkin


@router.post(
    "/elderly-profiles/{profile_id}/checkin-schedules",
    status_code=status.HTTP_201_CREATED,
    summary="Create a check-in schedule",
    description="Defines how often a check-in is expected (the recurring intent).",
)
def create_checkin_schedule(
    payload: CheckinScheduleCreate,
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> dict:
    """Create a check-in schedule for a resident."""
    schedule = CheckinSchedule(
        elderly_profile_id=profile.id,
        title=payload.title,
        checkin_type=_enum_value(payload.checkin_type),
        recurrence=_enum_value(payload.recurrence),
        time_of_day=payload.time_of_day,
        is_active=payload.is_active,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return {
        "id": schedule.id,
        "elderly_profile_id": schedule.elderly_profile_id,
        "title": schedule.title,
        "checkin_type": schedule.checkin_type,
        "recurrence": schedule.recurrence,
        "time_of_day": schedule.time_of_day,
        "is_active": schedule.is_active,
        "created_at": schedule.created_at,
    }
