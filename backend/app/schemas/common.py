"""Pydantic schemas — the shape of every request and response body.

Why these exist
---------------
The SQLAlchemy models describe the *database*. These schemas describe the
*API*. Keeping them separate means:

* We never accidentally expose a column like `password_hash` to the internet.
* Requests are validated before they reach business logic.
* FastAPI generates the OpenAPI documentation from these automatically.

Naming convention used throughout `backend/app/schemas/`:
    XxxCreate   -> the JSON body accepted when creating a row
    XxxUpdate   -> the JSON body accepted when changing a row (all optional)
    XxxRead     -> the JSON returned to the client
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response schemas that are built from SQLAlchemy objects.

    `from_attributes=True` lets Pydantic read attributes off an ORM instance
    (e.g. `User.email`) instead of requiring a dictionary.
    """

    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    """A simple message response (used for deletes and other no-content actions)."""

    detail: str = Field(..., examples=["Resident deleted."])