"""Schemas for elderly profiles and caregiver assignments.

Privacy note: these schemas deliberately contain no national ID, medical record
number, or address fields. Only care-relevant, non-identifying data is accepted.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from backend.app.models.enums import AssignmentRole
from backend.app.schemas.common import ORMModel

# ---------------------------------------------------------------------------
# Elderly profiles
# ---------------------------------------------------------------------------


class ElderlyProfileCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles`."""

    display_name: str = Field(..., min_length=1, max_length=120)
    date_of_birth: date | None = None
    room_label: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    mobility_notes: str | None = Field(default=None, max_length=255)
    linked_user_id: int | None = None

    @field_validator("display_name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Display name cannot be blank.")
        return value.strip()

    @field_validator("date_of_birth")
    @classmethod
    def dob_not_in_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Date of birth cannot be in the future.")
        return value


class ElderlyProfileUpdate(BaseModel):
    """Body for `PATCH /api/v1/elderly-profiles/{id}`.

    Every field is optional: only the ones provided are changed.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    date_of_birth: date | None = None
    room_label: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    mobility_notes: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Display name cannot be blank.")
        return value.strip() if value is not None else None


class ElderlyProfileRead(ORMModel):
    """An elderly profile as returned by the API."""

    id: int
    display_name: str
    date_of_birth: date | None = None
    room_label: str | None = None
    notes: str | None = None
    mobility_notes: str | None = None
    linked_user_id: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Caregiver assignments
# ---------------------------------------------------------------------------


class CaregiverAssignmentCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/caregivers`."""

    caregiver_id: int = Field(..., gt=0)
    assignment_role: AssignmentRole = AssignmentRole.SECONDARY
    is_active: bool = True


class CaregiverAssignmentUpdate(BaseModel):
    """Body for `PATCH /api/v1/caregiver-assignments/{id}`."""

    assignment_role: AssignmentRole | None = None
    is_active: bool | None = None


class CaregiverAssignmentRead(ORMModel):
    """A caregiver assignment, including the caregiver's display name for the UI."""

    id: int
    caregiver_id: int
    elderly_profile_id: int
    assignment_role: AssignmentRole
    is_active: bool
    assigned_at: datetime
    ended_at: datetime | None = None

    # Convenience fields resolved by the service layer so the frontend does not
    # need a second request just to show who a caregiver is.
    caregiver_display_name: str | None = None
    caregiver_email: str | None = None
