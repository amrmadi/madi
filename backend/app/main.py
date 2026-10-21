"""ElderLife AI — FastAPI application entry point.

Run it with::

    uvicorn backend.app.main:app --reload

Then open:
    * http://localhost:8000/docs       interactive Swagger UI
    * http://localhost:8000/redoc      alternative API reference
    * http://localhost:8000/openapi.json  the raw OpenAPI schema

This module builds the app, wires up CORS, attaches the error handlers, and
mounts every router.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import __version__
from backend.app.api.v1 import api_router
from backend.app.core.config import get_settings
from backend.app.core.errors import register_exception_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("elderlife")

settings = get_settings()

# Fail fast if production is misconfigured (e.g. default secret key).
settings.validate_secret_key()

API_DESCRIPTION = """
Backend API for **ElderLife AI**, a monitoring platform that helps caregivers
look after elderly people at home.

### What is implemented today
* Account registration and login (Argon2 password hashing, signed JWT access tokens)
* Role-based authorization (`admin`, `caregiver`, `elderly`, `analyst`)
* Elderly profiles and caregiver assignments, with **server-enforced** access rules
* Care plans, medication schedules, reminders, and check-ins
* Activity events and alerts

### What is NOT implemented yet
* AI/ML inference endpoints (fall detection, activity recognition, behavioural
  anomaly detection) — planned for Phase 6. There are deliberately no fake
  prediction endpoints.
* Password reset, email verification, and refresh tokens.
* Real-time (WebSocket) alert delivery.

### Authentication
Call `POST /api/v1/auth/login` to obtain a token, then send it on subsequent
requests as:

```
Authorization: Bearer <access_token>
```

### Access control
A caregiver can only read or change data for residents they are actively
assigned to. Administrators can access all residents. This is enforced on the
server for every relevant endpoint.
"""

app = FastAPI(
    title="ElderLife AI API",
    description=API_DESCRIPTION,
    version=__version__,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={"name": "ElderLife AI graduation project"},
    license_info={"name": "Academic project — see repository LICENSE"},
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# The browser blocks cross-origin requests unless the server opts in. The
# allowed origins come from ALLOWED_ORIGINS in `.env` (default: the Vite dev
# server on port 5173).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
# Gives every error a consistent {"error": {...}} body.
register_exception_handlers(app)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(api_router, prefix="/api/v1")

# Expose ONLY the health/version checks at the root as well, because Docker
# healthchecks and load balancers conventionally look there.
# Note: mounting the whole `api_router` here would duplicate every care
# endpoint under a second, unprefixed path — unnecessary surface area.
from backend.app.api.routers import health as _health_router  # noqa: E402

app.include_router(_health_router.router, include_in_schema=False)


@app.on_event("startup")
def log_startup() -> None:
    """Log the configuration on startup (never logs secrets)."""
    logger.info(
        "ElderLife AI API %s starting (environment=%s, docs at /docs)",
        __version__,
        settings.environment,
    )
    if settings.database_url.startswith("sqlite"):
        logger.warning(
            "Database backend is SQLite (%s). PostgreSQL is the intended "
            "production database.",
            settings.database_url.split("://", 1)[0],
        )
