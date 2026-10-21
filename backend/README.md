# `backend/` — API server

FastAPI + SQLAlchemy 2 + Alembic + Pydantic. Handles auth, role-based access,
elderly profiles, care plans, reminders, check-ins, activity events, alerts,
the alert-rule engine, KPIs and the AI inference endpoints (via `../ai/`).

## Run it (from the **repository root**, not from `backend/`)

```bash
python -m venv .venv
.venv\Scripts\activate                      # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r backend/requirements.txt
copy .env.example .env                      # Linux/macOS: cp .env.example .env
docker compose up -d db                     # PostgreSQL (see docker-compose.yml)
cd backend && alembic upgrade head && cd ..  # create tables
python -m backend.scripts.seed_demo         # optional demo data
uvicorn backend.app.main:app --reload       # http://localhost:8000/docs
```

## Tests (no PostgreSQL needed — they use in-memory SQLite)

```bash
python -m pytest backend/tests -v
```

## Layout

```
app/api/routers/   HTTP endpoints (auth, profiles, care, events, alert_engine, analytics, ai, health)
app/core/          settings, security (JWT/Argon2), dependencies, error handlers
app/models/        SQLAlchemy models        app/schemas/   Pydantic request/response models
app/services/      alert rules, alert service, KPI logic
alembic/           database migrations      scripts/       seed_demo.py
```

API contract: [`../docs/api-contract.md`](../docs/api-contract.md).
Never commit `.env` — only `.env.example`.
