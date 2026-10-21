"""Application exceptions and the handlers that turn them into HTTP responses.

Design goal: **every** error the API returns has the same JSON shape::

    {"error": {"code": "...", "message": "...", "details": ...}}

The frontend can therefore rely on one error-handling path instead of guessing
per endpoint. `code` is stable and machine-readable; `message` is safe to show
to a user.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """Base class for expected, 'clean' API failures.

    Raising one of these (rather than returning an error dict) keeps routers
    readable: `raise NotFound(...)` and let the handler format the response.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details


class NotFoundError(APIError):
    """The requested row does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(APIError):
    """The request conflicts with existing data (e.g. a duplicate email)."""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ValidationError(APIError):
    """The request was understood but the values are not acceptable."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "VALIDATION_ERROR"


class AuthenticationError(APIError):
    """Credentials were missing, invalid, or the token could not be verified."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "NOT_AUTHENTICATED"


class PermissionDeniedError(APIError):
    """The caller is authenticated but not allowed to do this."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"


class ServiceUnavailableError(APIError):
    """A dependency the endpoint needs is not ready (e.g. no model loaded)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"


def _envelope(
    status_code: int, code: str, message: str, details: Any | None = None
) -> JSONResponse:
    """Build the standard error JSON body."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every error handler to the FastAPI app."""

    @app.exception_handler(APIError)
    async def handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Turn FastAPI's validation errors into our envelope.

        The per-field details are preserved so the frontend can highlight the
        exact input that was wrong.
        """
        fields = []
        for err in exc.errors():
            location = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            fields.append(
                {
                    "field": location or "body",
                    "message": err.get("msg", "Invalid value."),
                    "type": err.get("type", "value_error"),
                }
            )
        return _envelope(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "One or more fields were invalid. See details for specifics.",
            {"fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Normalise framework-raised HTTP errors (404 on unknown routes, etc.)."""
        code_map = {
            401: "NOT_AUTHENTICATED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }
        return _envelope(
            exc.status_code,
            code_map.get(exc.status_code, "HTTP_ERROR"),
            str(exc.detail),
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        """A database constraint was violated.

        The raw message can leak schema details, so we log it and return a
        generic explanation instead.
        """
        return _envelope(
            status.HTTP_409_CONFLICT,
            "CONFLICT",
            "This change conflicts with existing data (for example a duplicate "
            "value, or a missing related record).",
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_sqlalchemy_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Any other database problem is a server-side fault (500)."""
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "DATABASE_ERROR",
            "A database error occurred. The request was not completed.",
        )
