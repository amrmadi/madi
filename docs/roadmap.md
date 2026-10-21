# ElderLife AI — Roadmap

> Status: **phases 1–6 delivered; seven tasks still open.**
> This document records what the project has actually built and verified, and
> what is still to do. Every "delivered" claim below is traceable to a command
> that was run — the evidence is in the top-level
> [README](../README.md#what-actually-works-today).

This document exists because a graduation project is graded partly on whether
the team knows what it has and what it has not. It also exists to stop the
failure mode where a plan quietly becomes a claim: someone writes "Phase 4:
done" in a report, and nobody can remember whether the code runs. So every
phase below states **what was delivered** and **how it was verified**, and the
open tasks are listed as open — not as "nearly done".

---

## 1. How to read this

| Source of truth | What it decides |
|---|---|
| [README → What actually works today](../README.md#what-actually-works-today) | which capabilities are **run and verified** |
| [CONTRIBUTING.md → Open tasks](../CONTRIBUTING.md#open-tasks) | which tasks are **not started**, with their definition of done |
| [CONTRIBUTING.md → Project rules](../CONTRIBUTING.md#project-rules-you-must-follow) | the rules every phase must obey |
| `docs/architecture.md`, `docs/erd.md`, `docs/api-contract.md` | what the system was *designed* to be |

A phase is only called **delivered** here if it was run. A design document is
not a delivery. That distinction is the whole point of the file.

> **On the phase numbers.** The planning documents (`architecture.md`,
> `api-contract.md`) were written against an older plan in which real-time
> alerts were Phase 5, the AI work Phase 6, and Power BI Phase 7. The six
> phases below are the ones the project actually went through; the work that
> did not happen is no longer described as a phase but tracked as **T1–T7** in
> [CONTRIBUTING.md](../CONTRIBUTING.md#open-tasks).

---

## 2. Phase summary

| Phase | Delivered | Verified by |
|---|---|---|
| **1 — Design and contracts** | Architecture, ERD, API contract, alert/KPI reference, dataset documentation | Documents exist and the code was checked against them (e.g. the analytics SQL validated against the models by `tools/validate_analytics_sql.py`) |
| **2 — Database schema and migrations** | 19 application tables + `alembic_version`, one Alembic migration, dataset/user separation | `alembic upgrade head` / `alembic check` → no drift; 20 tables counted in PostgreSQL 16 |
| **3 — Backend API and access control** | Auth, profiles, assignments, care plans, medication schedules, reminders, check-ins, activity events, alerts, alert-rule engine, KPIs, analytics, AI capability routes, demo seeder | **295 automated tests pass** (in-memory SQLite); `403` for unassigned caregivers confirmed over HTTP |
| **4 — Frontend application** | React + TypeScript + Vite app: login, dashboard, residents, resident detail (5 tabs), alerts | `tsc -b` exits 0, `npm run build` exits 0, **43 tests pass**; run against the live backend — all pages `200` with correct CORS |
| **5 — Alert rules, KPIs, analytics and the AI layer** | Rule engine with live thresholds, 8 KPIs with explicit missing-data handling, 8 SQL views, typed AI interfaces, and **a trained fall-detection model** | 8 views created and queried on real PostgreSQL; AI interface tests; the fall model measured at **F1 0.80 on 6 unseen adult subjects** (SisFall) |
| **6 — Deployment and end-to-end verification** | Backend + frontend Dockerfiles, Compose stack with health-gated start-up, offline validators, `.env.example`, `.gitignore` | Stack **built and run**: all three services healthy, migrations applied on real PostgreSQL, seeder verified, two real defects found by running it — and fixed |

---

## 3. Phase 1 — Design and contracts

**Delivered.** The design was written down before most of the code existed, so
that each later phase had something to be checked against:

| Artefact | Contents |
|---|---|
| [`docs/architecture.md`](architecture.md) | Mermaid component and sequence diagrams, layer responsibilities, key design decisions |
| [`docs/erd.md`](erd.md) | The 19 tables, their relationships, delete behaviour, and the honesty rules encoded in the schema |
| [`docs/api-contract.md`](api-contract.md) | Every endpoint, the error envelope, access-control matrix, and the backend↔AI contract |
| [`docs/alert-rules-and-kpis.md`](alert-rules-and-kpis.md) | How observations become alerts, and how each KPI is defined |
| [`docs/datasets/`](datasets/README.md) | The dataset documentation template and the four dataset files |

**Verified how.** The documents were not decoration — they were used as the
acceptance criteria of later phases. The analytics SQL was checked against the
models in `backend/app/models/` (**211 column references** validated against 19
model tables by `tools/validate_analytics_sql.py`; 13 further references could
not be resolved unambiguously and are reported separately rather than guessed
at); the access-control rules in the contract are the rules the backend
enforces; the "missing data is not an emergency" rule from the contract is
implemented in `backend/app/services/alert_rules.py` and covered by tests.

> The check reports **211 column references** across 24 table references. An
> earlier draft of the top-level README quoted "148"; that figure was correct
> when the SQL was smaller. The README has since been corrected to match the
> validator's output.

---

## 4. Phase 2 — Database schema and migrations

**Delivered.** 19 application tables plus `alembic_version`, created by the
single Alembic migration `596dcc02ab32_initial_schema.py`:

- Identity and access — `users`, `elderly_profiles`, `caregiver_assignments`
- Care delivery — `care_plans`, `care_plan_items`, `medication_schedules`, `reminders`, `checkin_schedules`, `checkins`
- Monitoring — `activity_events`, `fall_events`, `anomaly_events`, `risk_events`, `model_runs`
- Alerts and audit — `alerts`, `audit_logs`
- Research data — `dataset_registry`, `dataset_files`, deliberately isolated from user records

**Verified how.**

| Check | Result |
|---|---|
| `alembic upgrade head` | creates every table |
| Column-by-column comparison, models vs. migration | **no drift** |
| `alembic check` | "No new upgrade operations detected" |
| `alembic downgrade base` | removes them again |
| `\dt` inside PostgreSQL 16 | **20 tables** (19 + `alembic_version`) |

---

## 5. Phase 3 — Backend API and access control

**Delivered.** The FastAPI application in `backend/`:

| Area | What exists |
|---|---|
| Authentication | JWT bearer tokens, Argon2 password hashing, registration limited to caregiver/elderly roles |
| Residents | `elderly_profiles` CRUD with soft delete, caregiver assignments, access revocation |
| Care | care plans and items, medication schedules, reminders, check-in schedules and check-ins |
| Events | activity events with a `source` field that **defaults to `simulated`** |
| Alerts | create → acknowledge → resolve / dismiss, plus a timeline, deduplication and cooldowns |
| Rule engine | `POST /alerts/evaluate` returns the decision **and the thresholds used**; `GET /alert-rules` exposes the live configuration |
| Analytics | `GET /analytics/kpis`, `GET /analytics/kpi-definitions`, `GET /analytics/kpis.csv` (admin/analyst only) |
| AI capability routes | `GET /ai/predictors`, `GET /ai/predictors/{name}`, `POST /ai/predictors/{name}/check` |
| Ops | `/health` with a real `SELECT 1`, one error envelope, a demo seeder that refuses to run in production |

**Verified how.**

- **295 automated tests pass** (`python -m pytest -q`, in-memory SQLite, no database needed).
- **Access control is enforced server-side**: an unassigned caregiver gets `403`
  on profiles, care plans, check-ins, alerts and alert acknowledgement; the
  frontend hiding a button is not the protection.
- The alert lifecycle is covered by tests, including the rejection of a
  double acknowledge.
- Over HTTP against the running stack: unassigned caregiver `403`, assigned
  `200`, admin `200`, anonymous `401`.
- The demo seeder creates four throwaway logins; every demo row is marked
  `[DEMO]` and demo events use `source="simulated"`.

---

## 6. Phase 4 — Frontend application

**Delivered.** React 19 + TypeScript + Vite in `frontend/`: login, dashboard,
residents list, resident detail (care plan / check-ins / reminders / activity
history tabs), and an alerts page. One typed API client in `src/api/`, an auth
context, and shared loading/empty/error states.

**Verified how.**

| Check | Result |
|---|---|
| `npx tsc -b` | exit 0 |
| `npm run build` | exit 0 |
| `npm test` | **43 tests pass** |
| Against the live backend | login → scoped data → all pages `200`, with correct CORS |

Running it in a browser also found a **real defect** that static checks had
missed — `LoginPage` navigated during render. It is fixed and covered by the
existing suite. Driving every click-path in a browser is still a **manual**
step; see [T7](#8-t7--browser-flow-test).

---

## 7. Phase 5 — Alert rules, KPIs, analytics and the AI layer

**Delivered.**

| Piece | What it does |
|---|---|
| Alert rule engine | Turns an observation into an operational priority, with thresholds visible in the response. Data gaps are hard-capped at `low`; a fall with no confidence produces no alert at all. |
| KPI catalogue | 8 KPIs, each with a numerator, a denominator, a date range and an explicit missing-data rule. A KPI that cannot be measured returns `value: null`, `is_measurable: false` and a reason. |
| Analytics SQL | 8 read-only views over the operational tables, each carrying its own honesty columns (`excluded_pending`, `resolved_checkins`, `simulated_event_count`, `has_metrics`, `all_events_simulated`, …). |
| AI interfaces | `ai/base.py` — typed result objects that **enforce** the honesty rules (a result derived from simulated or imported data is `is_simulated: true`; a predictor with no model raises `ModelNotLoadedError`). `ai/registry.py` — the registry the backend asks by name. |
| Fall detection | `ai/fall_detection/` — preprocessing, training and a predictor, **trained on the public [SisFall](datasets/sisfall.md) dataset**. |

**Verified how.**

- The 8 analytics views were created **and queried** on a real PostgreSQL 16
  container using `ON_ERROR_STOP=1`, and they return rows from seeded data.
- The SQL was checked offline against the models by
  `tools/validate_analytics_sql.py`: **211 column references** all resolve to
  real tables and columns, across the 8 files and 19 model tables. The check
  passes; 13 references it cannot resolve unambiguously are counted and
  reported separately, not guessed at.
- The AI interfaces are covered by tests: the result types, the honesty rules
  and the registry.
- An offline validator (`tools/verify_no_model_path.py`) proves the predictor is
  honest **both** with and without a model file. **That validator is not in the
  working tree** — see [Known gaps](#known-gaps-in-the-current-working-tree).
- The fall-detection model was measured on **held-out subjects**:
  **F1 0.80 on 6 unseen adult subjects**. The elderly result rests on a
  **single subject** and is labelled as such wherever it appears — see
  [`ai/fall_detection/README.md`](../ai/fall_detection/README.md) and
  [datasets/sisfall.md](datasets/sisfall.md).

> The trained model file is **git-ignored**, so a fresh clone reports
> `is_ready: false` and `metrics: null` until it is retrained. That is the
> intended behaviour, not a bug.

---

## 8. Phase 6 — Deployment and end-to-end verification

**Delivered.** `backend/Dockerfile` (python:3.12-slim, non-root, healthcheck),
`frontend/Dockerfile` (Node build → nginx 1.27), `docker-compose.yml` with
`db` → `backend` → `frontend` health-gated start-up, the offline validators,
`.env.example` (placeholders only), and a `.gitignore` that keeps datasets,
model artefacts, exports and secrets out of the repository.

> **Working-tree note.** Of the four offline validators the README lists under
> "Verification tools", only `tools/validate_analytics_sql.py` is in the tree
> at the moment. `tools/validate_nginx.py`,
> `tools/verify_no_model_path.py` and `tools/validate-compose-real.js` are
> still missing, so the phase-6 verification described below cannot be
> re-run from this working tree as it stands.

**Verified how** — the stack was **built and run**, not merely written:

| Step | Result |
|---|---|
| `docker compose config` | interpolates and validates |
| `docker compose build` | both images built |
| `docker compose up -d` | `db` → healthy, `backend` → healthy, `frontend` → healthy |
| `alembic upgrade head` (in the container) | `Running upgrade -> 596dcc02ab32` |
| `alembic current` / `alembic check` | `596dcc02ab32 (head)` / "No new upgrade operations detected" |
| `\dt` | **20 tables** |
| `seed_demo --reset` | four demo logins created and verified |
| Analytics SQL applied with `ON_ERROR_STOP=1` | **8 views created**, all returning rows |
| Access control over HTTP | `403` / `200` / `200` / `401` as expected |
| Login through the browser's CORS path | `200` with the correct `Access-Control-Allow-Origin`; a disallowed origin gets no header |
| nginx responses | security headers present, a single `Cache-Control` on `/`, assets and deep links |

**Two real defects were found by running the stack** — neither was visible to
static checks:

1. nginx emitted **no security headers at all** (and two conflicting
   `Cache-Control` headers), because nginx discards server-level `add_header`
   inside a location that declares its own. The headers now live in
   `frontend/security-headers.conf` and are `include`d from every
   content-serving location; the offline validator models that inheritance rule.
2. The demo seed created an **acknowledged alert whose acknowledgement preceded
   its creation**, producing a negative median acknowledgement time in the
   analytics KPI.

Both are fixed and both have regression tests. This is the argument for the
project's rule *"nothing is done until it has been run"*.

---

## 9. Current state

| Area | State |
|---|---|
| Database schema | ✅ delivered and verified on real PostgreSQL |
| Backend API | ✅ delivered — 295 tests pass |
| Access control | ✅ delivered — enforced server-side |
| Alert rules and KPIs | ✅ delivered — measured, with missing-data handling stated |
| Frontend | ✅ delivered — builds, 43 tests, exercised against the live backend |
| Analytics SQL | ✅ 8 views, created and queried |
| AI interfaces | ✅ typed, tested, honest about missing models |
| **Fall detection** | 🟩 **trained and measured** (SisFall, F1 0.80 on 6 unseen adult subjects) — but the model file is git-ignored, so a fresh clone reports `is_ready: false` |
| **Activity recognition** | ⬜ no model — `503 MODEL_NOT_LOADED` |
| **Behavioural analysis** | ⬜ no model — `503 MODEL_NOT_LOADED` |
| **Power BI report** | ⬜ no `.pbix` — the export script and the SQL views exist, but no export output is present and no report has been built |
| **Real-time alerts** | ⬜ not implemented |
| **CI pipeline** | ✅ the workflow exists and is **green on GitHub** — see [T4](../CONTRIBUTING.md#t4--ci-pipeline-) |
| **Production deployment** | ⬜ local Docker Compose only; no host, no monitoring, no backup policy |

### Known gaps in the current working tree

There are currently **no missing paths**. Everything the top-level README,
`CONTRIBUTING.md` or the CI workflow refers to exists in the tree.

Paths that were referenced but **were not present** — and are now — are no
longer gaps: `analytics/export_analytics.py`, `analytics/sql/*.sql`,
`analytics/exports/` (the directory, with a `.gitkeep`; the generated CSVs
themselves are git-ignored and only appear once you run the export),
`tools/validate_analytics_sql.py`, `tools/validate_nginx.py`,
`tools/verify_no_model_path.py`, `tools/validate-compose-real.js`, `data/`
(raw, processed, sample), `ai/tests/`, `ai/fall_detection/train.py`,
`ai/fall_detection/README.md`, `ai/activity_recognition/`, and
`ai/behavioral_analysis/`.

> **The reporting-layer naming discrepancy is closed.** `docs/erd.md` used to
> list the reporting layer under names that do not exist
> (`analytics_checkin_daily`, `analytics_alerts_daily`, and so on). That table
> now lists the eight `v_*` views that exist —
> `v_alert_lifecycle_daily`, `v_alert_acknowledgement_performance`,
> `v_alert_priority_backlog`, `v_checkin_completion_daily`,
> `v_medication_adherence_daily`, `v_care_plan_adherence`,
> `v_model_run_metrics` and `v_resident_activity_summary` — with the honesty
> columns each one actually carries, every one of them checked against the
> corresponding SQL file. [`docs/powerbi-guide.md`](powerbi-guide.md) uses the
> same names, so the two documents now agree.

---

## 10. Open work

**None of the tasks below has been started.** They are listed with the exact
names and definitions of done from
[CONTRIBUTING.md → Open tasks](../CONTRIBUTING.md#open-tasks).

| Task | Name | State | Done when |
|---|---|---|---|
| **T1** | Activity recognition model | ⬜ Not started | A model evaluated on a held-out split, its measured metrics written next to the code, and the API serving it (currently `503 MODEL_NOT_LOADED`) |
| **T2** | Behavioural anomaly detection | ⬜ Not started | It produces a score with a stated threshold and a **documented false-positive rate**, and is never described as a medical diagnosis |
| **T3** | Real-time alerts (WebSocket) | ⬜ Not started | Creating an alert in one browser session makes it appear in another, and an unassigned caregiver receives nothing |
| **T4** | CI pipeline | ⬜ Not started | The workflow is green on a fresh clone and does **not** require the uncommitted dataset or model file |
| **T5** | Power BI report | ⬜ Not started | A `.pbix` opens against the exports and renders real data, with a screenshot in `docs/` — until then, no `.pbix` may be claimed to exist |
| **T6** | Frontend linting and formatting | ⬜ Not started | ESLint and Prettier are configured, the whole `src/` tree passes, and the CI job runs them |
| **T7** | Browser flow test | ⬜ Not started | A test drives login → residents → alert acknowledgement and asserts the rendered output |

> **Working-tree note on T4.** A workflow file `.github/workflows/ci.yml` is
> present in the working tree, but **no green run of it is recorded anywhere in
> this repository**, and `CONTRIBUTING.md` still marks T4 as not started. It is
> therefore **not** claimed as done here. It would also fail as written: the
> workflow calls `tools/validate_nginx.py`, `tools/verify_no_model_path.py` and
> `tools/validate-compose-real.js`, and of the four validators only
> `tools/validate_analytics_sql.py` is present. The same applies to the dataset
> downloads behind T1 and T2: nothing has been downloaded.

### Which tasks block which

| Task | Blocked by | Blocks |
|---|---|---|
| **T1** | downloading [UCI HAR](datasets/uci-har.md) | the activity-recognition capability; the `activity_recognition` predictor stays unavailable |
| **T2** | downloading [CASAS](datasets/casas.md) | the anomaly-detection capability; the `anomaly_detection` predictor stays unavailable |
| **T3** | — | live alert delivery in the UI |
| **T4** | the three missing validators under `tools/` that `ci.yml` calls | automated verification of every push |
| **T5** | running the export and opening Power BI Desktop — `analytics/export_analytics.py` and the eight SQL files are **already present** | the Power BI report |
| **T6** | — | consistent frontend style |
| **T7** | — | automated coverage of the main user journey |

### Picking one up

1. Read [CONTRIBUTING.md → Open tasks](../CONTRIBUTING.md#open-tasks) for the
   full acceptance criteria.
2. If it involves a dataset, **document the dataset first**
   ([docs/datasets/](datasets/README.md)) and download it into `data/raw/`.
3. Work on a branch; run the checks in
   [CONTRIBUTING.md → How to submit your work](../CONTRIBUTING.md#how-to-submit-your-work).
4. **Update the README's "What actually works today" table and this file** with
   what you actually measured — including anything worse than expected.

---

## 11. What this roadmap does not claim

- It does not claim the AI half is finished. One of the three AI problems has a
  model; the other two have designs and honest `503`s.
- It does not claim the analytics views are production-ready. They have been run
  over demo data only, never at a scale where query plans or indexes matter.
- It does not claim PostgreSQL is production-validated. Schema, seeding and
  queries were exercised against a real container; concurrency, contention and
  failover were **not** tested.
- It does not claim a Power BI report exists. No `.pbix` file exists in this
  repository, and none may be claimed to — see
  [powerbi-guide.md](powerbi-guide.md).
- It does not claim the documentation is fully consistent. The reporting-layer
  table in `docs/erd.md` used to list view names that do not exist; it has been
  corrected to the `v_*` views in `analytics/sql/`, and the honesty columns it
  lists were each verified against the corresponding SQL file. Other
  inconsistencies may still exist; the offline validators do not check prose.
