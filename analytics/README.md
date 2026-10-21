# Analytics

Read-only SQL views over the ElderLife AI database, plus a script that exports
them to CSV for a spreadsheet or a BI tool.

```
analytics/
    sql/               one file per view
    exports/           CSV output (git-ignored)
    export_analytics.py
```

## The views

| File | View | What it answers |
|------|------|-----------------|
| `sql/01_alert_lifecycle_daily.sql` | `v_alert_lifecycle_daily` | How many alerts were raised, acknowledged, resolved and dismissed each day? |
| `sql/02_alert_acknowledgement_performance.sql` | `v_alert_acknowledgement_performance` | How long does it take a caregiver to acknowledge an alert, and how many alerts are still open? |
| `sql/03_alert_priority_backlog.sql` | `v_alert_priority_backlog` | What is the current backlog, broken down by severity and alert type? |
| `sql/04_checkin_completion_daily.sql` | `v_checkin_completion_daily` | What share of scheduled check-ins were taken, missed, skipped or cancelled each day? |
| `sql/05_medication_adherence_daily.sql` | `v_medication_adherence_daily` | What share of scheduled medication doses were actually taken each day? |
| `sql/06_care_plan_adherence.sql` | `v_care_plan_adherence` | Which active care plans are being followed, and which are not? |
| `sql/07_model_run_metrics.sql` | `v_model_run_metrics` | Which model runs happened, how long did they take, and did they fail? |
| `sql/08_resident_activity_summary.sql` | `v_resident_activity_summary` | What activity, fall, anomaly and risk events were recorded per resident — and how many of them are simulated? |

Each file contains exactly two statements:

```sql
DROP VIEW IF EXISTS v_example;
CREATE OR REPLACE VIEW v_example AS ...;
```

The `DROP` comes first because `CREATE OR REPLACE VIEW` cannot change the
column list of an existing view. Re-running the file is therefore safe and
idempotent.

## Applying the views

```bash
# from the repository root, against a running database
python analytics/export_analytics.py --apply-sql
```

`--apply-sql` executes every file in `analytics/sql/` in filename order, which
is the order the views are designed to be applied in.

## Exporting to CSV

```bash
python analytics/export_analytics.py --database-url postgresql://user:pass@host:5432/elderlife
```

Writes one `<view>.csv` per view into `analytics/exports/`, plus
`_manifest.json` describing what was exported, from which SQL file, with how
many rows and which columns, and when (UTC, ISO-8601).

Useful flags:

| Flag | Meaning |
|------|---------|
| `--database-url` | Connection string. Defaults to `$DATABASE_URL`, then to the `.env.example` placeholder. |
| `--output-dir` | Where the CSVs go. Defaults to `analytics/exports`. |
| `--views` | Comma-separated subset of view names. Defaults to every view. |
| `--apply-sql` | Apply `analytics/sql/*.sql` before exporting. |

The script **never fabricates data**. If a view is missing from the database
it says so and exits non-zero rather than writing an empty file; if the
database is unreachable it exits non-zero with an actionable message. An empty
CSV would be indistinguishable from "this resident had no events", which is a
dangerous thing to invent.

## Checking the SQL without a database

```bash
python tools/validate_analytics_sql.py
```

The validator compares every table and column named in the SQL against the
SQLAlchemy models in `backend/app/models/`, which are the single source of
truth for the schema. It is completely offline.

## A note on simulated data

The seeded demo database contains rows whose `source` is `simulated`. Those
rows are marked as such in the data itself, and
`v_resident_activity_summary` exposes `simulated_event_count`,
`non_simulated_event_count` and `all_events_simulated` so that a report can
never present demo data as a measurement. The exported manifest carries the
same warning.

A view that mixes simulated and real rows does not hide the difference — it
counts it.
