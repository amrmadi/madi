"""Response envelope schemas shared by the whole API.

The API contract in `docs/api-contract.md` specifies a consistent error shape::

    {"error": {"code": "...", "message": "...", "details": null}}

Defining it once, here, is what makes that promise true for every endpoint.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    """The inner object describing what went wrong."""

    code: str = Field(
        ...,
        description="Stable machine-readable identifier the frontend may branch on.",
        examples=["ELDERLY_PROFILE_NOT_FOUND"],
    )
    message: str = Field(
        ...,
        description="Human-readable explanation, safe to show to a user.",
        examples=["Resident with id 42 does not exist."],
    )
    details: Any | None = Field(
        default=None,
        description="Optional extra context, e.g. per-field validation problems.",
    )


class ErrorResponse(BaseModel):
    """The full error envelope returned with every 4xx/5xx response."""

    error: ErrorBody


class Paginated(BaseModel, Generic[T]):
    """A page of results, matching the pagination rules in the API contract."""

    items: list[T]
    total: int = Field(..., description="Total matching rows, ignoring pagination.")
    page: int = Field(..., ge=1, description="Current page number (1-based).")
    page_size: int = Field(..., ge=1, description="Maximum rows per page.")
