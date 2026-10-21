# ElderLife AI — Architecture

> Status: **proposed design** (Phase 1). Nothing in this diagram is implemented yet.

## High-level diagram

```mermaid
flowchart TB
    subgraph CLIENT["Client layer"]
        UI["React + TypeScript (Vite)<br/>dashboard / residents / care plans / alerts"]
    end

    subgraph SERVER["Backend layer - FastAPI (Python)"]
        API["REST API - /api/v1"]
        WS["WebSocket /ws/alerts<br/>(real-time, planned Phase 5)"]
        SVC["Domain services<br/>residents, care plans,<br/>sensor data, alerts, analytics"]
    end

    subgraph AIMOD["AI layer - Python package, imported by the backend"]
        FALL["fall_detection<br/>(fall events)"]
        ACT["activity_recognition<br/>(activity labels)"]
        BEH["behavioral_analysis<br/>(routine anomalies)"]
    end

    subgraph DATA["Data layer"]
        PG[("PostgreSQL 16<br/>operational data")]
        RAW["data/raw<br/>downloaded datasets (git-ignored)"]
        PROC["data/processed<br/>cleaned features (git-ignored)"]
        MODELS["model artifacts<br/>(git-ignored)"]
    end

    BI["Analytics layer<br/>analytics/sql + analytics/exports<br/>imported by Power BI"]

    UI -->|"HTTPS + JSON"| API
    UI -.->|"real-time alerts (planned)"| WS
    API --> SVC
    SVC --> PG
    SVC --> FALL
    SVC --> ACT
    SVC --> BEH
    RAW --> PROC
    PROC -.->|"training (Phase 6, offline)"| MODELS
    MODELS -.->|"loaded at startup"| AIMOD
    FALL --> MODELS
    ACT --> MODELS
    BEH --> MODELS
    PG --> BI
    SVC --> BI
```

## Inference flow (sequence)

```mermaid
sequenceDiagram
    participant S as Sensor / device
    participant B as FastAPI backend
    participant A as AI modules (ai/)
    participant D as PostgreSQL
    participant F as Frontend

    S->>B: POST /api/v1/sensor-data (readings)
    B->>D: store raw reading
    B->>A: detect_fall(frame) / classify_activity(frame)
    A-->>B: result (label, confidence, occurred_at)
    B->>D: store event
    alt event is serious (e.g. fall, confidence > threshold)
        B->>D: create alert
        B-->>F: push alert via WebSocket (planned)
    end
    F->>B: GET /api/v1/alerts
    B-->>F: JSON list of alerts
```

## Layers and their responsibilities

| Layer | Folder | Responsibility |
|---|---|---|
| Client | `frontend/` | Renders the UI, calls the REST API, displays alerts. Contains **no** business logic and **no** ML code. |
| Backend | `backend/` | HTTP API, validation, permission-free domain logic (auth comes later), database access, and it *calls* the AI package. |
| AI | `ai/` | Pure Python functions: input data in → prediction out. No HTTP code, no database code. This keeps models testable in isolation. |
| Data | `data/` | Raw datasets (downloaded by hand), processed features (generated), small samples for tests. |
| Analytics | `analytics/` | SQL views that read PostgreSQL and exported CSV/Parquet files Power BI can import. |
| Docs | `docs/` | Architecture, API contract, roadmap, dataset documentation. |
| Tests | `tests/` | Automated tests that check the system behaves correctly. |

## Key design decisions

| Decision | Choice | Simple-language reason |
|---|---|---|
| Monorepo (one repo) | ✅ | One folder to share, one place to read the code — easier for a graduation project. |
| AI as a Python **package**, not a separate microservice | ✅ | FastAPI imports `ai/` directly. No extra server to run or debug. It can be split into a service later if needed. |
| Database access only through SQLAlchemy models | ✅ | One style of DB code everywhere; Alembic migrations keep the schema versioned. |
| JSON REST first, WebSocket later | ✅ | REST is easier to learn; real-time alerts are added once the basics work. |
| PostgreSQL in Docker | ✅ | The database runs the same on every machine and is easy to delete/recreate while learning. |
| Power BI via files/SQL views | ✅ | Power BI reads CSV/Parquet and SQL easily; no extra API is needed. |

## Data stores and their contents

- **PostgreSQL** — residents, care plans, sensor readings, events, alerts, model metadata.
  Everything the application needs while running.
- **`data/raw`** — the three public research datasets, downloaded manually. Never edited.
- **`data/processed`** — cleaned/encoded versions of those datasets, produced by scripts.
- **Model artifacts** (`*.pkl`, `*.pt`, ... under `ai/**/models/`) — trained model files.
  Git-ignored; they can always be recreated by re-running training scripts.

## External integrations (future, not implemented)

- Wearable / ambient sensors → `POST /api/v1/sensor-data` (simulated first).
- Email/SMS/push notifications for alerts (optional, Phase 5).
- Power BI Desktop connects to exported files or a read-only SQL view (Phase 7).
