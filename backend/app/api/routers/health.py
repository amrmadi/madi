"""Health and readiness endpoints.

These are used by Docker Compose healthchecks, by the frontend to show whether
the backend is reachable, and by developers to confirm the database connection.

Important: `/health` performs a real database round-trip. It reports
`"database": "disconnected"` rather than pretending everything is fine — a
health check that always says OK is worse than no health check.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app import __version__
from backend.app.core.config import get_settings
from backend.app.db.base import get_db

router = APIRouter(tags=["System"])


@router.get(
    "/health",
    summary="Check that the API and database are reachable",
    description=(
        "Returns the service status and verifies the database connection with a "
        "real query. When the database is unreachable this reports "
        "`database: \"disconnected\"` and a `degraded` status."
    ),
)
def health(db: Session = Depends(get_db)) -> dict:
    """Report service status and database connectivity."""
    settings = get_settings()
    database_state = "connected"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_state = "disconnected"

    return {
        "status": "ok" if database_state == "connected" else "degraded",
        "database": database_state,
        "version": __version__,
        "environment": settings.environment,
    }


@router.get(
    "/version",
    summary="Report the API version",
    description="Returns the application version and environment name.",
)
def version() -> dict:
    """Return the API version without touching the database."""
    settings = get_settings()
    return {"version": __version__, "environment": settings.environment}
