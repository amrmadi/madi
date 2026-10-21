"""FastAPI routers, grouped by domain.

Each module owns one area of the API and is mounted under `/api/v1` by
`backend/app/main.py`.
"""

from backend.app.api.routers import auth, care, events, health, profiles

__all__ = ["auth", "care", "events", "health", "profiles"]
