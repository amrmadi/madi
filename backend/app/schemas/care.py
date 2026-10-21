"""Schemas for care plans, their items, medications, reminders, and check-ins."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.models.enums import (
    CarePlanStatus,
    CheckinType,
    PlanItemKind,
    RecurrencePattern,
    ScheduleStatus,
)
from backend.app.schemas.common import ORMModel

# ---------------------------------------------------------------------------
# Care plans
# ---------------------------------------------------------------------------


class CarePlanCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/care-plans`."""

    title: str = Field(..., min_length=1, max_length=160)
    summary: str | None = None
    status: CarePlanStatus = CarePlanStatus.DRAFT
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank.")
        return value.strip()

    @model_validator(mode="after")
    def dates_ordered(self) -> "CarePlanCreate":
        """An end date must not come before the start date."""
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        return self


class CarePlanUpdate(BaseModel):
    """Body for `PATCH /api/v1/care-plans/{id}`."""

    title: str | None = Field(default=None, min_length=1, max_length=160)
    summary: str | None = None
    status: CarePlanStatus | None = None
    start_date: date | None = None
    end_date: date | None = None


class CarePlanRead(ORMModel):
    """A care plan as returned by the API."""

    id: int
    elderly_profile_id: int
    created_by_user_id: int | None = None
    title: str
    summary: str | None = None
    status: CarePlanStatus
    start_date: date | None = None
    end_date: date | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Medication schedules
# ---------------------------------------------------------------------------


class MedicationScheduleCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/medications`."""

    medication_name: str = Field(..., min_length=1, max_length=160)
    dosage_text: str | None = Field(default=None, max_length=120)
    instructions: str | None = None
    recurrence: RecurrencePattern = RecurrencePattern.DAILY
    time_of_day: str | None = Field(
        default=None, description="24-hour time, e.g. '08:00'.", examples=["08:00"]
    )
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool = True

    @field_validator("time_of_day")
    @classmethod
    def time_format(cls, value: str | None) -> str | None:
        """Validate 'HH:MM' in the API, mirroring the database CHECK constraint.

        Doing it here as well gives the user a clear message instead of a raw
        database error.
        """
        if value is None:
            return None
        parts = value.split(":")
        if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
            raise ValueError("time_of_day must look like 'HH:MM', for example '08:30'.")
        try:
            hours, minutes = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("time_of_day must contain numbers, for example '08:30'.")
        if not (0 <= hours <= 23) or not (0 <= minutes <= 59):
            raise ValueError("time_of_day must be a valid 24-hour time, e.g. '23:45'.")
        return value


class MedicationScheduleRead(ORMModel):
    """A medication schedule as returned by the API."""

    id: int
    elderly_profile_id: int
    medication_name: str
    dosage_text: str | None = None
    instructions: str | None = None
    recurrence: RecurrencePattern
    time_of_day: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


class ReminderCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/reminders`."""

    title: str = Field(..., min_length=1, max_length=160)
    message: str | None = None
    recurrence: RecurrencePattern = RecurrencePattern.DAILY
    time_of_day: str | None = None
    day_of_week: int | None = Field(
        default=None, ge=1, le=7, description="1 = Monday ... 7 = Sunday (weekly only)."
    )
    is_active: bool = True

    @field_validator("time_of_day")
    @classmethod
    def time_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split(":")
        if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
            raise ValueError("time_of_day must look like 'HH:MM', for example '08:30'.")
        try:
            hours, minutes = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("time_of_day must contain numbers, for example '08:30'.")
        if not (0 <= hours <= 23) or not (0 <= minutes <= 59):
            raise ValueError("time_of_day must be a valid 24-hour time, e.g. '23:45'.")
        return value

    @model_validator(mode="after")
    def weekly_needs_day(self) -> "ReminderCreate":
        """A weekly reminder without a weekday is ambiguous."""
        if self.recurrence == RecurrencePattern.WEEKLY and self.day_of_week is None:
            raise ValueError("A weekly reminder must include day_of_week (1-7).")
        return self


class ReminderRead(ORMModel):
    """A reminder as returned by the API."""

    id: int
    elderly_profile_id: int
    title: str
    message: str | None = None
    recurrence: RecurrencePattern
    time_of_day: str | None = None
    day_of_week: int | None = None
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------


class CheckinScheduleCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/checkin-schedules`."""

    title: str = Field(..., min_length=1, max_length=160)
    checkin_type: CheckinType = CheckinType.WELLBEING
    recurrence: RecurrencePattern = RecurrencePattern.DAILY
    time_of_day: str | None = None
    is_active: bool = True


class CheckinCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/checkins`."""

    checkin_type: CheckinType = CheckinType.MANUAL
    status: ScheduleStatus = ScheduleStatus.TAKEN
    scheduled_for: datetime | None = None
    performed_at: datetime | None = None
    wellbeing_note: str | None = None
    checkin_schedule_id: int | None = None


class CheckinRead(ORMModel):
    """A check-in record as returned by the API."""

    id: int
    elderly_profile_id: int
    checkin_schedule_id: int | None = None
    checkin_type: CheckinType
    status: ScheduleStatus
    scheduled_for: datetime | None = None
    performed_at: datetime | None = None
    wellbeing_note: str | None = None
    recorded_by_user_id: int | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Care plan items (generic, discriminated by item_kind)
# ---------------------------------------------------------------------------


class CarePlanItemRead(ORMModel):
    """One line on a care plan."""

    id: int
    care_plan_id: int
    item_kind: PlanItemKind
    title: str
    description: str | None = None
    is_active: bool
    medication_schedule_id: int | None = None
    reminder_id: int | None = None
    checkin_schedule_id: int | None = None
    created_at: datetime
