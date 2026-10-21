"""Endpoints for elderly profiles and caregiver assignments.

Access rules enforced here (on the server, as required):

* Any authenticated user may create a profile (a caregiver onboarding a new
  resident) — the creator is automatically assigned as the primary caregiver.
* Listing returns only profiles the caller may access.
* Reading/updating a profile requires an active assignment (or admin).
* Assigning and removing caregivers is restricted to admins and the profile's
  primary caregiver, so a secondary caregiver cannot remove others.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.deps import (
    accessible_profile_ids,
    get_current_user,
    is_admin,
    require_profile_access,
    NotFoundProfile,
)
from backend.app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from backend.app.db.base import get_db
from backend.app.models.enums import AssignmentRole, UserRole, UserStatus
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User
from backend.app.schemas.common import Message
from backend.app.schemas.profiles import (
    CaregiverAssignmentCreate,
    CaregiverAssignmentRead,
    CaregiverAssignmentUpdate,
    ElderlyProfileCreate,
    ElderlyProfileRead,
    ElderlyProfileUpdate,
)
from backend.app.schemas.responses import Paginated

router = APIRouter(tags=["Elderly profiles"])


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@router.get(
    "/elderly-profiles",
    response_model=Paginated[ElderlyProfileRead],
    summary="List residents you can access",
    description=(
        "Returns a page of residents.\n\n"
        "**Access:** a caregiver sees only residents they are actively assigned "
        "to. Administrators see all residents."
    ),
)
def list_elderly_profiles(
    page: int = Query(1, ge=1, description="Page number, starting at 1."),
    page_size: int = Query(50, ge=1, le=200, description="Rows per page (max 200)."),
    include_inactive: bool = Query(False, description="Include deactivated residents."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Paginated[ElderlyProfileRead]:
    """List the residents visible to the caller."""
    query = select(ElderlyProfile)
    count_query = select(func.count()).select_from(ElderlyProfile)

    # Restrict to the caller's scope. `None` means "no restriction" (admin).
    scope = accessible_profile_ids(db, current_user)
    if scope is not None:
        if not scope:
            # No assignments: return an empty page rather than every resident.
            return Paginated[ElderlyProfileRead](
                items=[], total=0, page=page, page_size=page_size
            )
        query = query.where(ElderlyProfile.id.in_(scope))
        count_query = count_query.where(ElderlyProfile.id.in_(scope))

    if not include_inactive:
        query = query.where(ElderlyProfile.is_active.is_(True))
        count_query = count_query.where(ElderlyProfile.is_active.is_(True))

    total = db.execute(count_query).scalar_one()
    rows = (
        db.execute(
            query.order_by(ElderlyProfile.display_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    return Paginated[ElderlyProfileRead](
        items=[ElderlyProfileRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/elderly-profiles",
    response_model=ElderlyProfileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a resident profile",
    description=(
        "Creates a resident profile. The creating caregiver is automatically "
        "assigned as that resident's **primary** caregiver, so they can "
        "immediately access the record they just created."
    ),
)
def create_elderly_profile(
    payload: ElderlyProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ElderlyProfile:
    """Create a profile and auto-assign the creator."""
    if payload.linked_user_id is not None:
        linked = db.get(User, payload.linked_user_id)
        if linked is None:
            raise NotFoundError(
                f"User with id {payload.linked_user_id} does not exist.",
                code="USER_NOT_FOUND",
            )
        # A login account can be linked to at most one profile.
        already = db.execute(
            select(ElderlyProfile).where(
                ElderlyProfile.linked_user_id == payload.linked_user_id
            )
        ).scalar_one_or_none()
        if already is not None:
            raise ConflictError(
                "That user account is already linked to another resident profile.",
                code="USER_ALREADY_LINKED",
            )

    profile = ElderlyProfile(
        display_name=payload.display_name,
        date_of_birth=payload.date_of_birth,
        room_label=payload.room_label,
        notes=payload.notes,
        mobility_notes=payload.mobility_notes,
        linked_user_id=payload.linked_user_id,
        is_active=True,
    )
    db.add(profile)
    db.flush()  # assigns profile.id without committing yet

    # Auto-assign the creator so the new record is immediately accessible.
    if current_user.role in (UserRole.CAREGIVER.value, UserRole.ADMIN.value):
        db.add(
            CaregiverAssignment(
                caregiver_id=current_user.id,
                elderly_profile_id=profile.id,
                assignment_role=AssignmentRole.PRIMARY.value,
                is_active=True,
            )
        )

    db.commit()
    db.refresh(profile)
    return profile


@router.get(
    "/elderly-profiles/{profile_id}",
    response_model=ElderlyProfileRead,
    summary="Read one resident",
    responses={
        403: {"description": "You are not assigned to this resident."},
        404: {"description": "No resident with that id."},
    },
)
def read_elderly_profile(
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
) -> ElderlyProfile:
    """Return a single profile the caller may access."""
    return profile


@router.patch(
    "/elderly-profiles/{profile_id}",
    response_model=ElderlyProfileRead,
    summary="Update a resident",
    description="Only the fields you provide are changed.",
    responses={403: {"description": "You are not assigned to this resident."}},
)
def update_elderly_profile(
    payload: ElderlyProfileUpdate,
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> ElderlyProfile:
    """Apply a partial update to a profile."""
    # `exclude_unset` distinguishes "field omitted" from "field set to null".
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


@router.delete(
    "/elderly-profiles/{profile_id}",
    response_model=Message,
    summary="Deactivate a resident",
    description=(
        "Performs a **soft delete**: the profile is marked inactive rather than "
        "removed, so historical events, alerts, and audit records stay intact "
        "and the underlying data is never destroyed accidentally."
    ),
    responses={403: {"description": "You are not assigned to this resident."}},
)
def deactivate_elderly_profile(
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    """Soft-delete a profile. Restricted to admins and primary caregivers."""
    if not is_admin(current_user):
        is_primary = db.execute(
            select(CaregiverAssignment).where(
                CaregiverAssignment.elderly_profile_id == profile.id,
                CaregiverAssignment.caregiver_id == current_user.id,
                CaregiverAssignment.assignment_role == AssignmentRole.PRIMARY.value,
                CaregiverAssignment.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if is_primary is None:
            raise PermissionDeniedError(
                "Only an administrator or the primary caregiver can deactivate a resident."
            )

    profile.is_active = False
    db.commit()
    return Message(detail=f"Resident {profile.id} has been deactivated.")


# ---------------------------------------------------------------------------
# Caregiver assignments
# ---------------------------------------------------------------------------


def _to_assignment_read(
    assignment: CaregiverAssignment, caregiver: User | None
) -> CaregiverAssignmentRead:
    """Convert an assignment to its API shape, enriching it with caregiver details."""
    result = CaregiverAssignmentRead.model_validate(assignment)
    if caregiver is not None:
        result.caregiver_display_name = caregiver.display_name
        result.caregiver_email = caregiver.email
    return result


@router.get(
    "/elderly-profiles/{profile_id}/caregivers",
    response_model=list[CaregiverAssignmentRead],
    summary="List caregivers assigned to a resident",
    responses={403: {"description": "You are not assigned to this resident."}},
)
def list_caregivers(
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    db: Session = Depends(get_db),
) -> list[CaregiverAssignmentRead]:
    """Return every caregiver linked to the resident."""
    rows = db.execute(
        select(CaregiverAssignment, User)
        .join(User, User.id == CaregiverAssignment.caregiver_id)
        .where(CaregiverAssignment.elderly_profile_id == profile.id)
        .order_by(CaregiverAssignment.assigned_at)
    ).all()
    return [_to_assignment_read(a, u) for a, u in rows]


@router.post(
    "/elderly-profiles/{profile_id}/caregivers",
    response_model=CaregiverAssignmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a caregiver to a resident",
    description=(
        "**Access:** only an administrator or the resident's primary caregiver "
        "may assign other caregivers."
    ),
    responses={
        403: {"description": "Only admins or the primary caregiver may do this."},
        409: {"description": "That caregiver is already assigned."},
    },
)
def assign_caregiver(
    payload: CaregiverAssignmentCreate,
    profile: ElderlyProfile = Depends(require_profile_access("profile_id")),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CaregiverAssignmentRead:
    """Create a caregiver assignment."""
    if not is_admin(current_user):
        is_primary = db.execute(
            select(CaregiverAssignment).where(
                CaregiverAssignment.elderly_profile_id == profile.id,
                CaregiverAssignment.caregiver_id == current_user.id,
                CaregiverAssignment.assignment_role == AssignmentRole.PRIMARY.value,
                CaregiverAssignment.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if is_primary is None:
            raise PermissionDeniedError(
                "Only an administrator or the primary caregiver can assign caregivers."
            )

    caregiver = db.get(User, payload.caregiver_id)
    if caregiver is None:
        raise NotFoundError(
            f"User with id {payload.caregiver_id} does not exist.",
            code="USER_NOT_FOUND",
        )
    if caregiver.status == UserStatus.DISABLED.value:
        raise ConflictError("That account is disabled and cannot be assigned.")

    existing = db.execute(
        select(CaregiverAssignment).where(
            CaregiverAssignment.caregiver_id == payload.caregiver_id,
            CaregiverAssignment.elderly_profile_id == profile.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            "That caregiver is already assigned to this resident.",
            code="ASSIGNMENT_EXISTS",
        )

    assignment = CaregiverAssignment(
        caregiver_id=payload.caregiver_id,
        elderly_profile_id=profile.id,
        assignment_role=payload.assignment_role.value,
        is_active=payload.is_active,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return _to_assignment_read(assignment, caregiver)


@router.patch(
    "/caregiver-assignments/{assignment_id}",
    response_model=CaregiverAssignmentRead,
    summary="Change a caregiver assignment",
    description=(
        "Change the role or deactivate an assignment. Deactivating is how access "
        "is **revoked** — the row is kept for history rather than deleted.\n\n"
        "**Access:** only an administrator or the resident's primary caregiver."
    ),
)
def update_assignment(
    assignment_id: int,
    payload: CaregiverAssignmentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CaregiverAssignmentRead:
    """Update the role or active flag of an assignment."""
    assignment = db.get(CaregiverAssignment, assignment_id)
    if assignment is None:
        raise NotFoundError(
            f"Caregiver assignment with id {assignment_id} does not exist.",
            code="ASSIGNMENT_NOT_FOUND",
        )

    profile = db.get(ElderlyProfile, assignment.elderly_profile_id)
    if profile is None:  # pragma: no cover - FK guarantees this
        raise NotFoundProfile(assignment.elderly_profile_id)

    # Authorisation: admin, or the primary caregiver on this profile.
    if not is_admin(current_user):
        is_primary = db.execute(
            select(CaregiverAssignment).where(
                CaregiverAssignment.elderly_profile_id == profile.id,
                CaregiverAssignment.caregiver_id == current_user.id,
                CaregiverAssignment.assignment_role == AssignmentRole.PRIMARY.value,
                CaregiverAssignment.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if is_primary is None:
            raise PermissionDeniedError(
                "Only an administrator or the primary caregiver can change assignments."
            )

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        # Coerce enums to their stored string values.
        setattr(assignment, field, value.value if hasattr(value, "value") else value)

    # Deactivating sets an end timestamp, so we can tell when access stopped.
    if changes.get("is_active") is False and assignment.ended_at is None:
        assignment.ended_at = datetime.now(timezone.utc)
    elif changes.get("is_active") is True:
        assignment.ended_at = None

    db.commit()
    db.refresh(assignment)

    caregiver = db.get(User, assignment.caregiver_id)
    return _to_assignment_read(assignment, caregiver)
