"""API schemas (Pydantic request/response models).

Importing this package does not touch the database; it only defines data shapes.
"""

from backend.app.schemas.auth import (
    TokenResponse,
    UserLogin,
    UserRead,
    UserRegister,
)
from backend.app.schemas.care import (
    CarePlanCreate,
    CarePlanItemRead,
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
from backend.app.schemas.common import Message, ORMModel
from backend.app.schemas.events import (
    ActivityEventCreate,
    ActivityEventRead,
    AlertAcknowledge,
    AlertCreate,
    AlertRead,
    AlertUpdate,
)
from backend.app.schemas.profiles import (
    CaregiverAssignmentCreate,
    CaregiverAssignmentRead,
    CaregiverAssignmentUpdate,
    ElderlyProfileCreate,
    ElderlyProfileRead,
    ElderlyProfileUpdate,
)
from backend.app.schemas.responses import ErrorBody, ErrorResponse, Paginated

__all__ = [
    # common
    "ORMModel",
    "Message",
    "ErrorBody",
    "ErrorResponse",
    "Paginated",
    # auth
    "UserRegister",
    "UserLogin",
    "UserRead",
    "TokenResponse",
    # profiles
    "ElderlyProfileCreate",
    "ElderlyProfileUpdate",
    "ElderlyProfileRead",
    "CaregiverAssignmentCreate",
    "CaregiverAssignmentUpdate",
    "CaregiverAssignmentRead",
    # care
    "CarePlanCreate",
    "CarePlanUpdate",
    "CarePlanRead",
    "CarePlanItemRead",
    "MedicationScheduleCreate",
    "MedicationScheduleRead",
    "ReminderCreate",
    "ReminderRead",
    "CheckinCreate",
    "CheckinRead",
    "CheckinScheduleCreate",
    # events
    "ActivityEventCreate",
    "ActivityEventRead",
    "AlertCreate",
    "AlertUpdate",
    "AlertRead",
    "AlertAcknowledge",
]
