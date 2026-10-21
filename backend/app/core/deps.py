"""Authentication and authorization dependencies for FastAPI routes.

How access control works in ElderLife AI
----------------------------------------
Authentication ("who are you?")
    The client sends `Authorization: Bearer <token>`. `get_current_user`
    verifies the token signature and loads the user from the database.

Authorization ("what may you do?")
    Two mechanisms, both enforced **on the server**:

    1. **Role checks** — `require_roles(...)` restricts an endpoint to, say,
       admins. Used for account management.

    2. **Caregiver access scoping** — `require_profile_access(...)` is the
       important one for care data. A caregiver may only read or change a
       resident's care records if an *active* `CaregiverAssignment` links them.
       Admins bypass this check by design.

Why server-side enforcement matters
-----------------------------------
The frontend can hide buttons, but hidden buttons are not security: anyone can
call the API directly. Every rule below is therefore checked again here, on the
server, regardless of what the UI shows.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.errors import AuthenticationError, PermissionDeniedError
from backend.app.core.security import decode_access_token
from backend.app.db.base import get_db
from backend.app.models.enums import AssignmentRole, UserRole, UserStatus
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User

# `auto_error=False` so we can raise our own consistent error envelope instead
# of FastAPI's default 403 body.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the `Authorization` header.

    Raises `AuthenticationError` (401) when the header is missing, the token is
    invalid/expired, or the account is disabled.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError(
            "Authentication required. Send an 'Authorization: Bearer <token>' header."
        )

    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise AuthenticationError(
            "Your session has expired. Please sign in again.",
            code="TOKEN_EXPIRED",
        )
    except jwt.InvalidTokenError:
        # Deliberately vague: never reveal *why* a token was rejected.
        raise AuthenticationError("The access token is invalid.")

    # Only access tokens may be used for authentication.
    if claims.get("type") != "access":
        raise AuthenticationError(
            "This token cannot be used for authentication.",
            code="WRONG_TOKEN_TYPE",
        )

    subject = claims.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise AuthenticationError("The access token is invalid.")

    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationError(
            "The account for this token no longer exists.",
            code="USER_NOT_FOUND",
        )

    if not user.is_active or user.status == UserStatus.DISABLED.value:
        raise AuthenticationError(
            "This account is disabled.", code="ACCOUNT_DISABLED"
        )

    # Expose the user id on the request for logging middleware (Phase 5).
    request.state.user_id = user.id
    return user


def require_roles(*allowed: UserRole) -> Callable[[User], User]:
    """Dependency factory: allow only the given roles.

    Usage::

        @router.get("/admin/users", dependencies=[Depends(require_roles(UserRole.ADMIN))])
    """
    allowed_values = {role.value for role in allowed}

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_values:
            raise PermissionDeniedError(
                "Your role does not permit this action.",
                details={"required_roles": sorted(allowed_values)},
            )
        return current_user

    return _checker


def is_admin(user: User) -> bool:
    """Admins may access any resident's data (needed for support and oversight)."""
    return user.role == UserRole.ADMIN.value


def get_accessible_profile(
    profile_id: int,
    db: Session,
    current_user: User,
) -> ElderlyProfile:
    """Return a profile the user may access, or raise the right error.

    Two distinct failures are reported, and the distinction matters:

    * profile does not exist      -> 404 NOT_FOUND
    * profile exists, no access   -> 403 PERMISSION_DENIED

    A caregiver with no assignment is told "permission denied" rather than
    "not found", because pretending it does not exist would be confusing for a
    legitimate user who simply has not been assigned yet.
    """
    profile = db.get(ElderlyProfile, profile_id)
    if profile is None:
        raise NotFoundProfile(profile_id)

    if is_admin(current_user):
        return profile

    # An elderly user may view their own profile.
    if profile.linked_user_id == current_user.id:
        return profile

    if current_user.role == UserRole.ANALYST.value:
        # Analysts get read-only access to anonymised aggregates, which are
        # served by the analytics endpoints (Phase 7). They may not read raw
        # care records, so they are intentionally excluded here.
        raise PermissionDeniedError(
            "Analyst accounts cannot access individual care records."
        )

    assignment = db.execute(
        select(CaregiverAssignment).where(
            CaregiverAssignment.elderly_profile_id == profile_id,
            CaregiverAssignment.caregiver_id == current_user.id,
            CaregiverAssignment.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if assignment is None:
        raise PermissionDeniedError(
            "You are not assigned to this resident, so you cannot access their records.",
            details={"elderly_profile_id": profile_id},
        )

    return profile


def NotFoundProfile(profile_id: int):  # noqa: N802 - reads like a class on purpose
    """Build a 404 for a missing elderly profile (kept as a helper for clarity)."""
    from backend.app.core.errors import NotFoundError

    return NotFoundError(
        f"Resident with id {profile_id} does not exist.",
        code="ELDERLY_PROFILE_NOT_FOUND",
    )


def require_profile_access(
    profile_id_param: str = "profile_id",
) -> Callable[..., ElderlyProfile]:
    """Dependency factory: ensure the caller may access `{profile_id}`.

    This is the main caregiver access restriction. Endpoints that touch a
    resident's care data declare it, so the rule is applied consistently rather
    than re-implemented in every route.
    """

    def _checker(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> ElderlyProfile:
        raw = request.path_params.get(profile_id_param)
        if raw is None:
            raise AuthenticationError(
                "Internal error: profile id missing from the request path."
            )
        try:
            profile_id = int(raw)
        except (TypeError, ValueError):
            from backend.app.core.errors import ValidationError

            raise ValidationError("The resident id in the URL must be a number.")
        return get_accessible_profile(profile_id, db, current_user)

    return _checker


def require_any_role(*roles: UserRole) -> Callable[[User], User]:
    """Alias of `require_roles` kept for readability at call sites."""
    return require_roles(*roles)


def accessible_profile_ids(db: Session, current_user: User) -> Sequence[int] | None:
    """Return the ids of every profile the user may see.

    Returns `None` to mean "no restriction" (admins), which lets list endpoints
    express the rule as a single query filter.
    """
    if is_admin(current_user):
        return None

    ids = (
        db.execute(
            select(CaregiverAssignment.elderly_profile_id).where(
                CaregiverAssignment.caregiver_id == current_user.id,
                CaregiverAssignment.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )

    # An elderly user also sees their own profile.
    own = (
        db.execute(
            select(ElderlyProfile.id).where(ElderlyProfile.linked_user_id == current_user.id)
        )
        .scalars()
        .all()
    )

    return list({*ids, *own})
