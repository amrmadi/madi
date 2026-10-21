# Contributing to ElderLife AI

This is a **graduation project**, so clarity matters more than cleverness. This
document tells you how to get the project running, how to check your work, and
exactly which tasks are still open.

> **Read this first:** [What actually works today](README.md#what-actually-works-today)
> in the README. It separates what has been *run and verified* from what is only
> *planned*. Please keep that distinction honest in anything you add.

---

## Contents

- [Before you start](#before-you-start)
- [Running the project](#running-the-project)
- [Running the tests](#running-the-tests)
- [Project rules you must follow](#project-rules-you-must-follow)
- [Open tasks](#open-tasks)
- [How to submit your work](#how-to-submit-your-work)
- [Troubleshooting your setup](#troubleshooting-your-setup)

---

## Before you start

| Tool | Version used here | Notes |
|---|---|---|
| Node.js | 20+ (verified on v24.13.1) | for the frontend |
| npm | 10+ (verified on 11.8.0) | comes with Node |
| Python | 3.11–3.13 recommended | 3.15 works but see the caveat below |
| Git | any recent | |
| Docker Desktop | only for the Compose stack | optional for day-to-day work |

**A note on Python 3.15.** The machine this was built on runs Python 3.15, which
is new enough that several packages have no pre-built wheel, so `pip` tries to
compile them from source and fails on Windows with
`Microsoft Visual C++ 14.0 or greater is required`. The project pins versions
that *do* have 3.15 wheels. **If you can use Python 3.12, do** — it removes the
constraint entirely, and the Docker image already uses 3.12.

```powershell
winget install --id Python.Python.3.12 --exact
```

---

## Running the project

The backend and frontend are **two separate processes**. Start the backend first.
Run every command from the **repository root** unless stated otherwise.

### 1. Backend

```powershell
# One-time: create the environment and install dependencies
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Create the database schema. Run from backend/ — alembic.ini lives there.
cd backend
$env:DATABASE_URL = "sqlite+pysqlite:///./elderlife_local_dev.db"
..\.venv\Scripts\alembic.exe upgrade head

# Start the API (keep DATABASE_URL set in this shell)
..\.venv\Scripts\uvicorn.exe backend.app.main:app --reload
```

- API: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

> `DATABASE_URL` defaults to **PostgreSQL**, which may not be installed on your
> machine. The SQLite line above is the quick path and needs nothing extra.

### 2. Demo data

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.seed_demo --reset
```

This prints four throwaway logins, all with password `DemoPassw0rd!23`:

| Email | Role |
|---|---|
| `admin@demo.elderlife.example` | admin — sees everything |
| `caregiver.a@demo.elderlife.example` | primary caregiver for Margaret |
| `caregiver.b@demo.elderlife.example` | secondary for Margaret, **primary for George** |
| `resident@demo.elderlife.example` | elderly login for Margaret |

Signing in as `caregiver.a` and then `caregiver.b` is the quickest way to see the
access control working: each sees a **different** list of residents, enforced on
the server.

> The seed script **refuses to run** when `ENVIRONMENT=production`.

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The frontend defaults to `http://localhost:8000`, so no `.env` file is needed.

> ⚠️ **Open the app at `http://localhost:5173`, not `http://127.0.0.1:5173`.**
> The backend's CORS allowlist names `localhost` explicitly, so the `127.0.0.1`
> form is blocked by the browser and every request will fail.

### 4. Optional — train the fall-detection model

The trained model file is **not committed** (~87 MB, git-ignored), so a fresh
clone reports fall detection as `is_ready: false`. This is expected and honest,
not a bug. To train it you first need the SisFall dataset — its source, size and
checksum are in [`docs/datasets/sisfall.md`](docs/datasets/sisfall.md).

```powershell
# after placing the archive at data\raw\SisFall_dataset.zip
.\.venv\Scripts\python.exe -m ai.fall_detection.train
```

Skipping this is fine. Everything else works, and the AI endpoints report the
model as unavailable rather than inventing a prediction.

---

## Running the tests

Two commands, both from the repository root (except the frontend one).

```powershell
# Backend + AI  — 289 tests, uses in-memory SQLite, needs no database
.\.venv\Scripts\python.exe -m pytest -q

# Frontend — 43 tests
cd frontend
npm test

# Type check + production build
npx tsc -b
npm run build
```

### Quick subset while developing

```powershell
# Just the access-control tests
.\.venv\Scripts\python.exe -m pytest backend\tests -v -k access

# Just the AI pipeline
.\.venv\Scripts\python.exe -m pytest ai\tests -v
```

### Offline validators

These are fast pre-flight checks that need no server. Each exits non-zero on
failure.

```powershell
.\.venv\Scripts\python.exe tools\validate_analytics_sql.py   # SQL names real tables/columns
.\.venv\Scripts\python.exe tools\validate_nginx.py           # nginx.conf structure
.\.venv\Scripts\python.exe tools\verify_no_model_path.py     # AI is honest with/without a model
node tools\validate-compose-real.js                          # compose + Dockerfile paths
```

**A green test run is not proof the feature works.** Several real defects in this
project were invisible to static checks and only appeared when the stack was
actually run. If you change Docker, nginx, or the seed script, **run the thing**.

---

## Project rules you must follow

These are not style preferences — they are the rules that keep the project
trustworthy. They are enforced in code and covered by tests where possible.

### 1. Never present simulated data as real

- Demo rows are marked `[DEMO]`; demo events use `source="simulated"`.
- Any result derived from a public research dataset is flagged
  `is_simulated: true`, so it can never be shown as a resident's own reading.
- Public research datasets live in `data/`, are git-ignored, and are kept
  **strictly separate** from application user records.

### 2. A missing measurement is not an emergency

Missing check-ins or silence must never be escalated as a dangerous event — they
are capped at `low` severity. Alert `severity` is an **operational triage
priority** (how urgently a person should look), **not** a validated medical risk.

### 3. An unavailable capability says so

A predictor with no model reports `is_ready: false` and `metrics: null`, and
`POST /api/v1/ai/predictors/{name}/check` returns **`503 MODEL_NOT_LOADED`**. It
must never return a plausible-looking guess. The same goes for KPIs: when the
denominator is zero the API returns `value: null` with `is_measurable: false`
and a stated reason, rather than inventing a number.

### 4. No secrets, no personal data

- Real credentials never live in the repository — only in your local `.env`.
- `.env.example` contains **placeholders only**.
- Never enter real personal or medical information into the demo.

### 5. Nothing is "done" until it has been run

Update the README and `docs/roadmap.md` with what you **measured**, including
results that are worse than expected. Negative results are still results; hidden
ones are not.

---

## Open tasks

Each task lists a definition of done. Pick one, open an issue or branch, and
keep the change focused.

### T1 — Activity recognition model ⬜

**Goal:** a trained model that classifies daily activities (walking, sitting,
lying, standing, …).

- Dataset: **UCI HAR** — document it in `docs/datasets/uci-har.md` **before**
  downloading (the file exists but is still marked `To verify`).
- Add `ai/activity_recognition/` following the structure of
  `ai/fall_detection/` (`preprocess.py`, `train.py`, `predictor.py`).
- Wire it into `ai/registry.py` so `activity_recognition` stops returning
  `503 MODEL_NOT_LOADED`.
- **Done when:** the model is evaluated on a held-out split, its measured metrics
  are written into a README next to the code, and the API serves it.

### T2 — Behavioural anomaly detection ⬜

**Goal:** flag unusual routines that may indicate a health change.

- Dataset: **CASAS** — document it in `docs/datasets/casas.md` first.
- Suggested approach: a per-resident routine baseline (IsolationForest, or
  simple statistics over activity sequences).
- **Done when:** it produces a score with a stated threshold and a documented
  false-positive rate. Do **not** report an accuracy number you did not measure,
  and do not describe the output as a medical diagnosis.

### T3 — Real-time alerts (WebSocket) ⬜

**Goal:** a new alert appears in the UI without a page refresh.

- Add `/ws/alerts` to the backend, respecting the **same access rules** as the
  REST endpoints (a caregiver must only receive alerts for residents they are
  assigned to — do not leak other residents' alerts over the socket).
- Subscribe from the frontend and prepend new alerts to the list.
- **Done when:** creating an alert in one browser session makes it appear in
  another, and an unassigned caregiver receives nothing.

### T4 — CI pipeline ✅

**Goal:** tests run automatically on every push.

- Add `.github/workflows/` running: `pytest`, `npm test`, `npx tsc -b`,
  `npm run build`, and the offline validators.
- **Done when:** the workflow is green on a fresh clone, and it does **not**
  require the uncommitted dataset or model file (those tests must skip cleanly).

**What exists now:** `.github/workflows/ci.yml` has three jobs.

| Job | Runs |
|---|---|
| `backend` | `python -m pytest -q` (295 tests) and the three offline Python validators |
| `frontend` | `npm test`, `npx tsc -b`, `npm run build` |
| `compose` | `node tools/validate-compose-real.js` and `docker compose config --quiet` |

**How it was verified, locally, on this machine:**

```powershell
.\.venv\Scripts\python.exe -m pytest -q                    # 295 passed, 4 skipped
.\.venv\Scripts\python.exe tools\validate_analytics_sql.py # PASS — 211 column references
.\.venv\Scripts\python.exe tools\validate_nginx.py         # PASS — 34 checks
.\.venv\Scripts\python.exe tools\verify_no_model_path.py   # PASS — 73 checks
node tools\validate-compose-real.js                        # PASS — 26 checks
cd frontend; npm test; npx tsc -b; npm run build            # 43 tests, 0 type errors
```

The 4 skipped tests are the ones that need a trained model file. They skip
cleanly rather than failing, which is what the "done when" clause requires.

**Still to do:** the workflow has not yet run on GitHub. The first push
triggers it; if it goes red there, the local command above that corresponds
to the failing step is the one to re-run.

### T5 — Power BI report ⬜

**Goal:** a report built on the existing CSV exports.

- `analytics/export_analytics.py` already writes one CSV per view plus a
  `_manifest.json` recording provenance. See `docs/powerbi-guide.md`.
- **Done when:** a `.pbix` opens against the exports and renders real data, and a
  screenshot is added to `docs/`. Until then no `.pbix` may be claimed to exist.

### T6 — Frontend linting and formatting ⬜

**Goal:** consistent code style.

- `package.json` currently maps `lint` to `tsc --noEmit` — there is **no ESLint
  or Prettier config**.
- **Done when:** ESLint and Prettier are configured, the whole `src/` tree
  passes, and the CI job from T4 runs them.

### T7 — Browser flow test ⬜

**Goal:** automated coverage of a full user journey.

- The 43 frontend tests cover the HTTP client, format helpers, and page states,
  but not one happy-path journey from login to alert acknowledgement.
- **Done when:** a test drives login → residents → alert acknowledgement and
  asserts the rendered output.

---

## How to submit your work

1. **Branch off.** Use a descriptive name: `feature/activity-recognition`,
   `fix/alert-scoping`.
2. **Keep commits focused.** One task per branch where you can.
3. **Run the checks before you push:**
   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   cd frontend; npx tsc -b; npm test
   ```
4. **Do not remove working tests** to make a suite pass. If a test is genuinely
   wrong, say so in the pull request and explain why.
5. **Write an honest commit message.** Say what changed, what you ran, and what
   you observed. If something is unverified, say that.
6. **Update the docs** you invalidated — especially the README's
   "What actually works today" table and `docs/roadmap.md`.

### Commit message style

```
Short summary in the imperative mood

What changed and why. Mention the commands you actually ran and their
results, including any number you are claiming.

If something is deliberately NOT done or NOT verified, say so here.
```

---

## Troubleshooting your setup

| Symptom | Cause | Fix |
|---|---|---|
| `No config file 'alembic.ini' found` | alembic run from the wrong folder | `cd backend` first |
| `connection refused` to the database | no PostgreSQL running | Use SQLite: `$env:DATABASE_URL = "sqlite+pysqlite:///./elderlife_local_dev.db"` |
| `ModuleNotFoundError: No module named 'backend'` | wrong working directory | Run from the repository root |
| `ModuleNotFoundError: No module named 'ai'` | running the backend from outside the repo root | The API imports the local `ai` package; run from the repo root |
| Every frontend request fails with a CORS error | you opened `127.0.0.1:5173` instead of `localhost:5173` | Use <http://localhost:5173> |
| Login returns `422` for a demo account | the account predates the demo-domain fix | Re-seed: `python -m backend.scripts.seed_demo --reset` |
| `Microsoft Visual C++ 14.0 or greater is required` | no Python wheel for your version | Install Python 3.12 and recreate `.venv` |
| Port `8000` / `5173` already in use | another process holds the port | Stop the other process, or change the port |
| Tests skip with "SisFall archive not downloaded" | the dataset is git-ignored and absent | Expected on a fresh clone — this is not a failure |

For container-specific problems, see the troubleshooting table in the
[main README](README.md#troubleshooting).
