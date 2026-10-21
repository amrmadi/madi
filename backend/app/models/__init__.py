"""ORM models for ElderLife AI.

Importing this package registers every model on `Base.metadata`.
**Alembic depends on this**: `alembic/env.py` imports this module so
`--autogenerate` can see the full schema. Adding a new model file therefore
requires adding it to the imports below.

Tables and the phase that introduces them:

    identity.py   users, elderly_profiles, caregiver_assignments
    care.py       care_plans, care_plan_items, medication_schedules,
                  medication_dose_logs, reminders, checkin_schedules, checkins
    events.py     model_runs, activity_events, fall_events, anomaly_events,
                  risk_events
    alerts.py     alerts, audit_logs
    datasets.py   dataset_registry, dataset_files  (research data isolation)
"""

from backend.app.db.base import Base
from backend.app.models.alerts import Alert, AuditLog
from backend.app.models.care import (
    CarePlan,
    CarePlanItem,
    Checkin,
    CheckinSchedule,
    MedicationDoseLog,
    MedicationSchedule,
    Reminder,
)
from backend.app.models.datasets import KNOWN_DATASETS, DatasetFile, DatasetRegistry
from backend.app.models.enums import (
    ActivityType,
    AlertStatus,
    AlertType,
    AssignmentRole,
    CarePlanStatus,
    CheckinType,
    EventSource,
    ModelRunStatus,
    ModelTask,
    PlanItemKind,
    RecurrencePattern,
    RiskCategory,
    ScheduleStatus,
    SeverityLevel,
    UserRole,
    UserStatus,
)
from backend.app.models.events import (
    ActivityEvent,
    AnomalyEvent,
    FallEvent,
    ModelRun,
    RiskEvent,
)
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User

__all__ = [
    # base
    "Base",
    # identity
    "User",
    "ElderlyProfile",
    "CaregiverAssignment",
    # care
    "CarePlan",
    "CarePlanItem",
    "MedicationSchedule",
    "MedicationDoseLog",
    "Reminder",
    "CheckinSchedule",
    "Checkin",
    # events / AI
    "ModelRun",
    "ActivityEvent",
    "FallEvent",
    "AnomalyEvent",
    "RiskEvent",
    # alerts / audit
    "Alert",
    "AuditLog",
    # datasets
    "DatasetRegistry",
    "DatasetFile",
    "KNOWN_DATASETS",
    # enums
    "UserRole",
    "UserStatus",
    "AssignmentRole",
    "CarePlanStatus",
    "PlanItemKind",
    "RecurrencePattern",
    "ScheduleStatus",
    "SeverityLevel",
    "AlertStatus",
    "AlertType",
    "EventSource",
    "ModelRunStatus",
    "ModelTask",
    "CheckinType",
    "ActivityType",
    "RiskCategory",
]
