"""Schemas for activity events, alerts, and audit logs.

Honesty requirement encoded here: every event schema exposes a `source` field,
and the API defaults it to `simulated`. A client cannot silently submit data
that looks like a real sensor reading without stating where it came from.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.models.enums import (
    ActivityType,
    AlertStatus,
    AlertType,
    EventSource,
    SeverityLevel,
)
from backend.app.schemas.common import ORMModel

# ---------------------------------------------------------------------------
# Activity events
# ---------------------------------------------------------------------------


class ActivityEventCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/activity-events`."""

    activity_type: ActivityType
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Model confidence, 0.0-1.0."
    )
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    room_label: str | None = Field(default=None, max_length=32)
    note: str | None = None
    # Defaults to "simulated" so demo data is never mistaken for real readings.
    source: EventSource = EventSource.SIMULATED

    @model_validator(mode="after")
    def end_after_start(self) -> "ActivityEventCreate":
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot be earlier than started_at.")
        return self


class ActivityEventRead(ORMModel):
    """An activity event as returned by the API."""

    id: int
    elderly_profile_id: int
    model_run_id: int | None = None
    activity_type: ActivityType
    confidence: float | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    source: EventSource
    room_label: str | None = None
    note: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertCreate(BaseModel):
    """Body for `POST /api/v1/elderly-profiles/{id}/alerts`.

    Normally alerts are raised automatically by the monitoring pipeline
    (Phase 5). This endpoint exists so a caregiver can record one manually.
    """

    alert_type: AlertType
    severity: SeverityLevel = SeverityLevel.MEDIUM
    title: str = Field(..., min_length=1, max_length=160)
    message: str | None = None


class AlertUpdate(BaseModel):
    """Body for `PATCH /api/v1/alerts/{id}` — typically an acknowledgement."""

    status: AlertStatus | None = None
    message: str | None = None

    @field_validator("status")
    @classmethod
    def only_known_statuses(cls, value: AlertStatus | None) -> AlertStatus | None:
        # Enumerated already by the type; kept explicit for clarity in the docs.
        return value


class AlertRead(ORMModel):
    """An alert as returned by the API."""

    id: int
    elderly_profile_id: int
    alert_type: AlertType
    severity: SeverityLevel
    status: AlertStatus
    title: str
    message: str | None = None
    source_event_type: str | None = None
    source_event_id: int | None = None
    occurrence_count: int
    created_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by_user_id: int | None = None
    resolved_at: datetime | None = None

    # Resolved by the service layer so the alerts list can show who it is about.
    elderly_profile_name: str | None = None


class AlertAcknowledge(BaseModel):
    """Optional body for `POST /api/v1/alerts/{id}/acknowledge`."""

    note: str | None = None
