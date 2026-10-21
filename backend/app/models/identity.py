"""Identity and relationships: users, elderly profiles, caregiver assignments.

Design notes
------------
* `users` holds login/account data. A user may be a caregiver, an elderly
  person, an analyst, or an admin (`UserRole`).
* `elderly_profiles` holds care-related information about a monitored person.
  It is deliberately **separate** from `users`: a profile can exist before the
  person ever gets a login, and care data must be deleted independently of an
  account.
* `caregiver_assignments` is the many-to-many join between the two, with extra
  columns (role, dates) so it is a proper association object rather than a bare
  join table.

Privacy: no national IDs, medical record numbers, addresses, or other direct
identifiers are stored. Display names are a label only.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, utcnow
from backend.app.models.enums import AssignmentRole, UserRole, UserStatus


class User(Base):
    """An account that can sign in to ElderLife AI.

    `password_hash` and `is_email_verified` are placeholders for Phase 4
    authentication. No authentication is implemented yet, and no real secret is
    ever seeded.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default=UserRole.CAREGIVER.value
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=UserStatus.ACTIVE.value
    )

    # NULL until authentication is implemented (Phase 4). Never seeded.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ---- Relationships ----
    assignments: Mapped[list["CaregiverAssignment"]] = relationship(
        back_populates="caregiver", cascade="all, delete-orphan"
    )
    owned_profile: Mapped["ElderlyProfile | None"] = relationship(
        back_populates="linked_user", uselist=False
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'caregiver', 'elderly', 'analyst')",
            name="user_role_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'invited', 'disabled')",
            name="user_status_valid",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} email={self.email!r} role={self.role}>"


class ElderlyProfile(Base):
    """Care-related record for one monitored elderly person."""

    __tablename__ = "elderly_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    room_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional link to a login account if the person uses the app themselves.
    linked_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True
    )

    # Flags that later phases read to tune models / alerting sensitivity.
    mobility_notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ---- Relationships ----
    linked_user: Mapped["User | None"] = relationship(back_populates="owned_profile")
    caregiver_assignments: Mapped[list["CaregiverAssignment"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )
    care_plans: Mapped[list["CarePlan"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )
    checkins: Mapped[list["Checkin"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )
    activity_events: Mapped[list["ActivityEvent"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )
    fall_events: Mapped[list["FallEvent"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )
    anomaly_events: Mapped[list["AnomalyEvent"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )
    risk_events: Mapped[list["RiskEvent"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="elderly_profile", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ElderlyProfile id={self.id} name={self.display_name!r}>"


class CaregiverAssignment(Base):
    """Links a caregiver `User` to an `ElderlyProfile`.

    This is an association object (not a plain join table) because the
    relationship itself carries data: the caregiver's role, when they started,
    and whether they are still active on this case.
    """

    __tablename__ = "caregiver_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    caregiver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    assignment_role: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AssignmentRole.SECONDARY.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- Relationships ----
    caregiver: Mapped["User"] = relationship(back_populates="assignments")
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="caregiver_assignments")

    __table_args__ = (
        # A caregiver is assigned to a given elderly profile only once.
        UniqueConstraint(
            "caregiver_id", "elderly_profile_id", name="caregiver_elderly_unique"
        ),
        CheckConstraint(
            "assignment_role IN ('primary', 'secondary', 'emergency', 'observer')",
            name="assignment_role_valid",
        ),
        Index("ix_assignments_profile_active", "elderly_profile_id", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<CaregiverAssignment caregiver={self.caregiver_id} "
            f"profile={self.elderly_profile_id} role={self.assignment_role}>"
        )
