"""Authentication endpoints: register, login, and read the current user."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.deps import get_current_user
from backend.app.core.errors import ConflictError, ValidationError
from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.db.base import get_db
from backend.app.models.enums import UserRole, UserStatus
from backend.app.models.identity import User
from backend.app.schemas.auth import (
    TokenResponse,
    UserLogin,
    UserRead,
    UserRegister,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _issue_token(user: User) -> TokenResponse:
    """Build the login response for a user."""
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        role=user.role,
        expires_minutes=settings.access_token_expire_minutes,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a caregiver account",
    description=(
        "Creates a new account and returns an access token.\n\n"
        "**Role restriction:** self-registration always creates a `caregiver`. "
        "Admin and analyst accounts must be created by an existing admin, so "
        "nobody can grant themselves extra privileges."
    ),
    responses={409: {"description": "An account with this email already exists."}},
)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> TokenResponse:
    """Register a new caregiver account."""
    existing = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            "An account with this email address already exists.",
            code="EMAIL_ALREADY_REGISTERED",
        )

    if payload.role not in (UserRole.CAREGIVER, UserRole.ELDERLY):
        raise ValidationError(
            "Self-registration is only available for caregiver or elderly accounts."
        )

    user = User(
        email=payload.email.lower(),
        display_name=payload.display_name,
        phone=payload.phone,
        role=payload.role.value,
        status=UserStatus.ACTIVE.value,
        # Only the hash is stored. The plain password is never persisted or logged.
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _issue_token(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in and receive an access token",
    description=(
        "Exchanges an email address and password for a signed access token. "
        "Send it on later requests as `Authorization: Bearer <token>`."
    ),
    responses={401: {"description": "Email or password is incorrect."}},
)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate a user and return a token."""
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()

    # Deliberately identical error for "no such user" and "wrong password", so
    # an attacker cannot use this endpoint to discover which emails exist.
    if user is None or not user.password_hash:
        raise_auth_failure()

    if not verify_password(payload.password, user.password_hash or ""):
        raise_auth_failure()

    if not user.is_active or user.status == UserStatus.DISABLED.value:
        raise_auth_failure(code="ACCOUNT_DISABLED", message="This account is disabled.")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    return _issue_token(user)


def raise_auth_failure(
    code: str = "INVALID_CREDENTIALS",
    message: str = "Email or password is incorrect.",
) -> None:
    """Raise the standard 401 for a failed login attempt."""
    from backend.app.core.errors import AuthenticationError

    raise AuthenticationError(message, code=code)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Read the signed-in user",
    description="Returns the profile of the account identified by the access token.",
)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's own record."""
    return current_user
