"""Aggregate router for API version 1.

Everything is mounted under `/api/v1` by `backend/app/main.py`. Keeping the
version prefix in one place means a future `/api/v2` can be added alongside
without touching individual routers.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.routers import (
    ai,
    alert_engine,
    analytics,
    auth,
    care,
    events,
    health,
    profiles,
)

api_router = APIRouter()

# Health sits at the root of the version prefix (/api/v1/health) but is also
# mounted at /health in main.py for infrastructure checks.
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(profiles.router)
api_router.include_router(care.router)
api_router.include_router(events.router)
api_router.include_router(alert_engine.router)
api_router.include_router(analytics.router)
api_router.include_router(ai.router)
