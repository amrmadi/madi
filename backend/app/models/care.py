"""Care domain: care plans, their items, medication schedules, reminders, check-ins.

How the pieces fit together
---------------------------
    ElderlyProfile 1 ── n CarePlan 1 ── n CarePlanItem
                                             │
                       ┌─────────────────────┼──────────────────────┐
                       ▼                     ▼                      ▼
              MedicationSchedule       Reminder           CheckinSchedule
                       │                     │                      │
                       ▼                     ▼                      ▼
                 (dose occurrences)   (reminder occurrences)  Checkin (actual record)

* `CarePlan` is the container: goals for a resident over a period of time.
* `CarePlanItem` is one line on the plan, tagged with `item_kind` so a plan can
  mix medications, reminders, and check-in schedules. Only the matching child
  table is populated for each kind.
* The `..._schedule` tables describe *repeating intent* (what should happen).
* `Checkin` (and future dose logs) record *what actually happened*.

Splitting intent from occurrence is what keeps the data normalised: changing a
schedule never rewrites history.
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
from backend.app.models.enums import (
    TIME_OF_DAY_CHECK,
    CarePlanStatus,
    CheckinType,
    PlanItemKind,
    RecurrencePattern,
    ScheduleStatus,
)


class CarePlan(Base):
    """A set of care goals for one elderly profile over a period of time."""

    __tablename__ = "care_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Who created the plan (audit trail; nullable so removing a user is not blocked).
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CarePlanStatus.DRAFT.value
    )

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ---- Relationships ----
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="care_plans")
    items: Mapped[list["CarePlanItem"]] = relationship(
        back_populates="care_plan", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'completed', 'cancelled')",
            name="care_plan_status_valid",
        ),
        # An end date must not precede the start date.
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="care_plan_dates_ordered",
        ),
        Index("ix_care_plans_profile_status", "elderly_profile_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CarePlan id={self.id} title={self.title!r} status={self.status}>"


class CarePlanItem(Base):
    """One line on a care plan: a medication, reminder, check-in, or note.

    `item_kind` is the discriminator. Exactly one of the nullable foreign keys
    is populated, matching the kind — enforced by a check constraint below.
    """

    __tablename__ = "care_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    care_plan_id: Mapped[int] = mapped_column(
        ForeignKey("care_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )

    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Exactly one of these is set, based on `item_kind`.
    medication_schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("medication_schedules.id", ondelete="CASCADE"), nullable=True
    )
    reminder_id: Mapped[int | None] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"), nullable=True
    )
    checkin_schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("checkin_schedules.id", ondelete="CASCADE"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    care_plan: Mapped["CarePlan"] = relationship(back_populates="items")
    medication_schedule: Mapped["MedicationSchedule | None"] = relationship(
        back_populates="plan_items"
    )
    reminder: Mapped["Reminder | None"] = relationship(back_populates="plan_items")
    checkin_schedule: Mapped["CheckinSchedule | None"] = relationship(
        back_populates="plan_items"
    )

    __table_args__ = (
        CheckConstraint(
            "item_kind IN ('medication', 'reminder', 'checkin', 'note')",
            name="care_plan_item_kind_valid",
        ),
        # The discriminator must agree with which foreign key is populated.
        CheckConstraint(
            "(item_kind = 'medication' AND medication_schedule_id IS NOT NULL"
            " AND reminder_id IS NULL AND checkin_schedule_id IS NULL)"
            " OR (item_kind = 'reminder' AND reminder_id IS NOT NULL"
            " AND medication_schedule_id IS NULL AND checkin_schedule_id IS NULL)"
            " OR (item_kind = 'checkin' AND checkin_schedule_id IS NOT NULL"
            " AND medication_schedule_id IS NULL AND reminder_id IS NULL)"
            " OR (item_kind = 'note' AND medication_schedule_id IS NULL"
            " AND reminder_id IS NULL AND checkin_schedule_id IS NULL)",
            name="care_plan_item_target_matches_kind",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CarePlanItem id={self.id} kind={self.item_kind} title={self.title!r}>"


class MedicationSchedule(Base):
    """A medication and how often it should be taken.

    This is *intent*, not history. Storing the drug name as free text keeps the
    schema free of medical coding systems; no dosage advice is generated by the
    system.
    """

    __tablename__ = "medication_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    medication_name: Mapped[str] = mapped_column(String(160), nullable=False)
    dosage_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    recurrence: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RecurrencePattern.DAILY.value
    )
    # Local wall-clock time of day, e.g. "08:00". Simple and readable for a
    # beginner project; a full timezone-aware scheduler is out of scope here.
    time_of_day: Mapped[str | None] = mapped_column(String(5), nullable=True)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    plan_items: Mapped[list["CarePlanItem"]] = relationship(back_populates="medication_schedule")
    dose_logs: Mapped[list["MedicationDoseLog"]] = relationship(
        back_populates="medication_schedule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "recurrence IN ('once', 'daily', 'weekly', 'monthly', 'as_needed')",
            name="medication_recurrence_valid",
        ),
        CheckConstraint(
            TIME_OF_DAY_CHECK,
            name="medication_time_of_day_format",
        ),
        Index("ix_medication_schedules_profile_active", "elderly_profile_id", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MedicationSchedule id={self.id} name={self.medication_name!r}>"


class MedicationDoseLog(Base):
    """What actually happened for one scheduled dose.

    Keeping occurrences in their own table lets us report adherence over time
    without touching the schedule definition.
    """

    __tablename__ = "medication_dose_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    medication_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("medication_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ScheduleStatus.SCHEDULED.value
    )
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Relationships ----
    medication_schedule: Mapped["MedicationSchedule"] = relationship(back_populates="dose_logs")

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'taken', 'missed', 'skipped', 'cancelled')",
            name="dose_log_status_valid",
        ),
        Index("ix_dose_logs_schedule_time", "medication_schedule_id", "scheduled_for"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MedicationDoseLog id={self.id} status={self.status}>"


class Reminder(Base):
    """A recurring reminder that is not a medication (hydration, exercise, ...).

    This is the *schedule*; individual occurrences will be logged in Phase 5
    when notification delivery exists.
    """

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    recurrence: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RecurrencePattern.DAILY.value
    )
    time_of_day: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # 1 = Monday ... 7 = Sunday; only meaningful when recurrence = 'weekly'.
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    plan_items: Mapped[list["CarePlanItem"]] = relationship(back_populates="reminder")

    __table_args__ = (
        CheckConstraint(
            "recurrence IN ('once', 'daily', 'weekly', 'monthly', 'as_needed')",
            name="reminder_recurrence_valid",
        ),
        CheckConstraint(
            "day_of_week IS NULL OR (day_of_week BETWEEN 1 AND 7)",
            name="reminder_day_of_week_range",
        ),
        CheckConstraint(
            TIME_OF_DAY_CHECK,
            name="reminder_time_of_day_format",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Reminder id={self.id} title={self.title!r}>"


class CheckinSchedule(Base):
    """How often a wellbeing/safety check-in is expected."""

    __tablename__ = "checkin_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    checkin_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CheckinType.WELLBEING.value
    )
    recurrence: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RecurrencePattern.DAILY.value
    )
    time_of_day: Mapped[str | None] = mapped_column(String(5), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    plan_items: Mapped[list["CarePlanItem"]] = relationship(back_populates="checkin_schedule")
    checkins: Mapped[list["Checkin"]] = relationship(
        back_populates="checkin_schedule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "checkin_type IN ('manual', 'automatic', 'wellbeing', 'safety')",
            name="checkin_schedule_type_valid",
        ),
        CheckConstraint(
            "recurrence IN ('once', 'daily', 'weekly', 'monthly', 'as_needed')",
            name="checkin_schedule_recurrence_valid",
        ),
        CheckConstraint(
            TIME_OF_DAY_CHECK,
            name="checkin_schedule_time_of_day_format",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CheckinSchedule id={self.id} title={self.title!r}>"


class Checkin(Base):
    """One actual check-in record."""

    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checkin_schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("checkin_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )

    checkin_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CheckinType.MANUAL.value
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ScheduleStatus.SCHEDULED.value
    )

    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Free-text, not a clinical score. Phases 5+ may add structured scales.
    wellbeing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="checkins")
    checkin_schedule: Mapped["CheckinSchedule | None"] = relationship(back_populates="checkins")

    __table_args__ = (
        CheckConstraint(
            "checkin_type IN ('manual', 'automatic', 'wellbeing', 'safety')",
            name="checkin_type_valid",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'taken', 'missed', 'skipped', 'cancelled')",
            name="checkin_status_valid",
        ),
        Index("ix_checkins_profile_time", "elderly_profile_id", "performed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Checkin id={self.id} type={self.checkin_type} status={self.status}>"
