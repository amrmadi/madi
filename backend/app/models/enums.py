"""Shared enumeration types used by several models.

These are stored as plain strings (`native_enum=False`) rather than PostgreSQL
ENUM types on purpose:
    * Adding a new value later is a one-line code change, not a migration that
      rewrites a database type.
    * The SQL is identical across PostgreSQL and SQLite, which keeps tests fast.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String-valued enum base class.

    Subclassing `str` makes members JSON-serialisable and directly comparable
    to plain strings, which keeps the API layer (Phase 3) simple.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# Portable SQL check for an "HH:MM" 24-hour time string
# ---------------------------------------------------------------------------
# PostgreSQL has a regex operator (`~`), but SQLite does not — using it made
# the schema impossible to create in the SQLite test database
# (`sqlite3.OperationalError: near "~": syntax error`).
#
# The expression below uses only standard SQL string functions that both
# engines implement, so the same constraint works in development, in tests,
# and in production:
#
#   * length is exactly 5
#   * character 3 is ':'
#   * hours are '00'-'23'
#   * minutes are '00'-'59'
#
# It is deliberately simple and readable rather than a clever one-liner.
TIME_OF_DAY_CHECK = (
    "time_of_day IS NULL OR ("
    "length(time_of_day) = 5"
    " AND substr(time_of_day, 3, 1) = ':'"
    " AND substr(time_of_day, 1, 2) BETWEEN '00' AND '23'"
    " AND substr(time_of_day, 4, 2) BETWEEN '00' AND '59'"
    " AND substr(time_of_day, 1, 1) BETWEEN '0' AND '9'"
    " AND substr(time_of_day, 2, 1) BETWEEN '0' AND '9'"
    " AND substr(time_of_day, 4, 1) BETWEEN '0' AND '9'"
    " AND substr(time_of_day, 5, 1) BETWEEN '0' AND '9'"
    ")"
)


class UserRole(StrEnum):
    """What a user account is allowed to do (enforced from Phase 4 onward)."""

    ADMIN = "admin"
    CAREGIVER = "caregiver"
    ELDERLY = "elderly"
    ANALYST = "analyst"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    DISABLED = "disabled"


class AssignmentRole(StrEnum):
    """The relationship between a caregiver and an elderly profile."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    EMERGENCY = "emergency"
    OBSERVER = "observer"


class CarePlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PlanItemKind(StrEnum):
    """Which kind of row a `care_plan_items` record points at.

    A care plan is a container of heterogeneous items (medication, reminder,
    check-in, note...). A discriminator column plus nullable foreign keys is
    the normalised way to model that without duplicating schedule columns.
    """

    MEDICATION = "medication"
    REMINDER = "reminder"
    CHECKIN = "checkin"
    NOTE = "note"


class RecurrencePattern(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    AS_NEEDED = "as_needed"


class ScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    TAKEN = "taken"
    MISSED = "missed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class SeverityLevel(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class AlertType(StrEnum):
    FALL = "fall"
    ANOMALY = "anomaly"
    RISK = "risk"
    MISSED_MEDICATION = "missed_medication"
    MISSED_CHECKIN = "missed_checkin"
    SYSTEM = "system"


class EventSource(StrEnum):
    """Where a recorded event came from.

    `SIMULATED` exists so that demo/test data can never be mistaken for real
    sensor readings — an honesty requirement of this project.
    """

    SIMULATED = "simulated"
    SENSOR = "sensor"
    MANUAL_ENTRY = "manual_entry"
    IMPORTED_DATASET = "imported_dataset"
    MODEL = "model"


class ModelRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelTask(StrEnum):
    """The three AI problems of the project."""

    FALL_DETECTION = "fall_detection"
    ACTIVITY_RECOGNITION = "activity_recognition"
    BEHAVIORAL_ANALYSIS = "behavioral_analysis"


class CheckinType(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    WELLBEING = "wellbeing"
    SAFETY = "safety"


class ActivityType(StrEnum):
    """Baseline activity vocabulary shared with `ai/activity_recognition`."""

    WALKING = "walking"
    STANDING = "standing"
    SITTING = "sitting"
    LYING = "lying"
    EATING = "eating"
    SLEEPING = "sleeping"
    TOILETING = "toileting"
    UNKNOWN = "unknown"


class RiskCategory(StrEnum):
    FALL_RISK = "fall_risk"
    MALNUTRITION = "malnutrition"
    DEHYDRATION = "dehydration"
    COGNITIVE_DECLINE = "cognitive_decline"
    SOCIAL_ISOLATION = "social_isolation"
    MEDICATION_ADHERENCE = "medication_adherence"
    GENERAL = "general"
