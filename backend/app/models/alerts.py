"""Alerting and auditing: alerts raised for caregivers, and audit logs.

Why `alerts` references its cause polymorphically
-------------------------------------------------
A fall, an anomaly, a missed medication, or a missed check-in can all raise an
alert. Rather than four nullable foreign keys, we store
`(source_event_type, source_event_id)` — a *soft* reference validated in
application code.

Trade-off, stated honestly: a soft reference cannot be enforced by the database
with a foreign key, so deleting a fall event would leave a dangling id. We accept
that because event rows are effectively append-only history; the alternative
(importing a PostgreSQL ENUM plus four nullable FKs) adds complexity without
real benefit for this project.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, utcnow
from backend.app.models.enums import AlertStatus, AlertType, SeverityLevel


class Alert(Base):
    """Something a caregiver should look at."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SeverityLevel.MEDIUM.value
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AlertStatus.NEW.value
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Soft reference to the triggering row (see module docstring).
    # Allowed values: 'fall_events', 'anomaly_events', 'risk_events',
    # 'checkins', 'medication_dose_logs'.
    source_event_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Set when the *same* underlying problem is re-detected, so the UI can
    # group recurring notifications instead of spamming the caregiver.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- Relationships ----
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="alerts")

    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('fall', 'anomaly', 'risk', 'missed_medication',"
            " 'missed_checkin', 'system')",
            name="alert_type_valid",
        ),
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="alert_severity_valid",
        ),
        CheckConstraint(
            "status IN ('new', 'acknowledged', 'resolved', 'dismissed')",
            name="alert_status_valid",
        ),
        CheckConstraint(
            "source_event_type IS NULL OR source_event_type IN"
            " ('fall_events', 'anomaly_events', 'risk_events', 'checkins',"
            " 'medication_dose_logs')",
            name="alert_source_event_type_valid",
        ),
        # Acknowledging and acknowledging-at must agree.
        CheckConstraint(
            "(status = 'new' AND acknowledged_at IS NULL)"
            " OR (status IN ('acknowledged', 'resolved', 'dismissed'))",
            name="alert_acknowledgement_consistent",
        ),
        Index("ix_alerts_profile_status", "elderly_profile_id", "status"),
        Index("ix_alerts_status_severity", "status", "severity"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Alert id={self.id} type={self.alert_type} status={self.status}>"


class AuditLog(Base):
    """Append-only record of significant actions.

    Written by the service layer (Phase 3+) whenever someone changes important
    data. It is intentionally generic: `action`, `entity_type`, `entity_id`, and
    a JSON string of changes, so we do not need a new table per entity.

    Privacy rule: never store personal or clinical values in `details_json` —
    only field names and identifiers.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Nullable: system actions (migrations, scheduled jobs) have no actor.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Where the action came from, useful for security review later.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuditLog id={self.id} action={self.action} entity={self.entity_type}>"
