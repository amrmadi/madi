"""Authentication schemas: registration, login, and token payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.models.enums import UserRole, UserStatus
from backend.app.schemas.common import ORMModel

# Password policy, kept simple and explicit so error messages can explain it.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class UserRegister(BaseModel):
    """Body for `POST /api/v1/auth/register`."""

    email: EmailStr
    display_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    phone: str | None = Field(default=None, max_length=32)
    # Self-registration is limited to the caregiver role. Admin accounts are
    # created by an existing admin, so nobody can grant themselves privileges.
    role: UserRole = UserRole.CAREGIVER

    @field_validator("password")
    @classmethod
    def password_not_trivially_weak(cls, value: str) -> str:
        """Reject a few obviously-weak passwords with a helpful message."""
        if value.lower() in {"password", "12345678", "password1", "qwertyui", "changeme"}:
            raise ValueError(
                "This password is too common. Choose something less predictable."
            )
        return value

    @field_validator("display_name")
    @classmethod
    def display_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Display name cannot be blank.")
        return value.strip()


class UserLogin(BaseModel):
    """Body for `POST /api/v1/auth/login`."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class UserRead(ORMModel):
    """A user as returned by the API. Never includes `password_hash`."""

    id: int
    email: EmailStr
    display_name: str
    phone: str | None = None
    role: UserRole
    status: UserStatus
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TokenResponse(BaseModel):
    """Body returned by a successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds.")
    user: UserRead
