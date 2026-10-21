# Alert rules and KPIs

This document is the plain-language reference for the two things Phase 6 adds:
the **alert rule engine** and the **KPI definitions**. The code is the source of
truth; this explains what it does and why.

- Engine (pure logic): `backend/app/services/alert_rules.py`
- Persistence: `backend/app/services/alert_service.py`
- KPI definitions: `backend/app/services/kpi_definitions.py`
- KPI computation: `backend/app/services/kpi_service.py`

---

## 1. Two ideas that everything else follows from

### 1.1 Operational priority is not medical risk

The engine produces an **operational priority**: how quickly a caregiver should
*look* at something. It answers "should a person check on this soon?" — nothing
more.

It is **not** a diagnosis and **not** a validated risk score. A "critical" alert
means *a human should look now*, not *the resident is medically critical*.

The database keeps these apart too:

| Concept | Where it lives | Who produces it |
|---|---|---|
| Operational priority | `alerts.severity` | the rule engine |
| Validated risk | `risk_events` (with `was_verified`) | a human / validated assessment |
| Human confirmation of an event | `fall_events.was_verified`, `anomaly_events.was_verified` | a person |

Only a **verified** risk assessment can reach HIGH priority. Unverified numbers
stay at MEDIUM, so unvalidated inputs cannot drive triage.

### 1.2 Missing data alone must never imply an emergency

If a sensor goes quiet, a check-in is not recorded, or a fall detection arrives
with no confidence value, the system knows **less**, not **worse**. Escalating
silence to an emergency teaches caregivers to ignore alarms.

So:

- A data gap has a **hard priority ceiling** (`low` by default). It can never be
  `critical`, no matter how long the gap lasts.
- A fall with **no confidence value** produces no alert at all — it is recorded
  as `suppressed_no_data`.
- Unsupervised anomalies are capped at `medium`: they are hints, not conclusions.

---

## 2. The rules

Each rule reads its thresholds from a `RuleConfig` object, and every decision
returns the thresholds it used (`applied_thresholds`), so the reasoning is always
inspectable.

| Observation | Default priority | Can it reach `critical`? | Notes |
|---|---|---|---|
| `fall` — verified by a person | `critical` | ✅ yes | The only path to `critical` |
| `fall` — unverified, confidence ≥ 0.60 | `high` | ❌ no | Labelled "unverified" everywhere |
| `fall` — confidence 0.30–0.60 | *(no alert)* | ❌ | Recorded for review |
| `fall` — confidence < 0.30 | *(no alert)* | ❌ | Treated as noise |
| `fall` — no confidence value | *(no alert)* | ❌ | **Missing data is not evidence** |
| `data_gap` ≥ 6 h | `low` | ❌ **hard cap** | Data-quality issue, explicitly not an emergency |
| `missed_checkin` past 2 h grace | `medium` | ❌ capped at `high` | Escalates with repeats |
| `missed_medication` | `medium` | ❌ capped at `high` | Escalates at 3 consecutive misses |
| `anomaly` score ≥ 2.0 | `low` | ❌ capped at `medium` | ≥ 3.5 → `medium` |
| `risk` — verified, score ≥ 7.0 | `high` | ❌ no | Validated assessment |
| `risk` — unverified | `medium` | ❌ no | Unvalidated stays at medium |

### Thresholds (defaults)

All of these are configurable via `RuleConfig` without editing the engine:

| Setting | Default |
|---|---|
| `fall_min_confidence` | 0.60 |
| `fall_report_floor` | 0.30 |
| `data_gap_mention_after` | 6 hours |
| `data_gap_max_priority` | `low` |
| `checkin_grace_period` | 2 hours |
| `anomaly_min_score` | 2.0 |
| `anomaly_high_score` | 3.5 |
| `anomaly_max_priority` | `medium` |
| `risk_high_score` | 7.0 |
| `default_cooldown` | 30 minutes |
| `fall_cooldown` | 15 minutes |

`GET /api/v1/alert-rules` returns the live configuration, so you can inspect what
the running system is actually using.

---

## 3. Deduplication

One event should produce one alert, not a stream of them.

Every alert carries a `dedupe_key` identifying *the same underlying problem*.
When an alert with the same key is still inside its **cooldown window**
(15 min for falls, 30 min otherwise), a new observation does **not** create a
second alert: it increments `occurrence_count` on the existing one.

```
19:00:02  fall detected (confidence 0.91)  -> new alert #42, occurrence_count = 1
19:00:07  same fall re-reported            -> alert #42, occurrence_count = 2
19:00:19  same fall re-reported            -> alert #42, occurrence_count = 3
(19:30+)  fall detected again              -> NEW alert, a genuinely new event
```

The caregiver sees "the same problem, three times", not three separate pages.

---

## 4. The alert lifecycle

```
        ┌─────────────┐
        │     new     │  raised by the engine (or by hand)
        └──────┬──────┘
               │
      ┌────────┼─────────┐
      ▼        ▼         ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│acknowledged│ │  resolved  │ │ dismissed  │
└────────────┘ └────────────┘ └────────────┘
   seen by        dealt with     judged to need
   a caregiver    and closed     no action
```

| Action | Endpoint | Sets |
|---|---|---|
| Acknowledge | `POST /alerts/{id}/acknowledge` | `status`, `acknowledged_at`, `acknowledged_by_user_id` |
| Resolve | `POST /alerts/{id}/resolve` | the above, plus `status = resolved`, `resolved_at` |
| Dismiss | `POST /alerts/{id}/dismiss` | `status = dismissed` |
| Inspect | `GET /alerts/{id}/timeline` | returns all three timestamps |

**Dismissing keeps the row.** A dismissed alert is the raw material for a
false-alarm rate; deleting it would make the system look better than it is.
Resolving an alert that was never acknowledged acknowledges it too, because a
resolved alert was by definition seen.

A database constraint enforces consistency: `status = 'new'` requires
`acknowledged_at IS NULL`, and any closed status requires it to be set. An alert
cannot be in an impossible state.

---

## 5. The KPIs

Every KPI is defined by a **numerator**, a **denominator**, a **date range**, and
a statement of **how missing data is handled**. The full text for each lives in
`backend/app/services/kpi_definitions.py` and is exposed at
`GET /api/v1/analytics/kpi-definitions`.

| KPI | Numerator | Denominator | Missing-data handling |
|---|---|---|---|
| `alert_acknowledgement_rate` | alerts with `acknowledged_at` | all alerts | Unacknowledged alerts stay in the denominator; they lower the rate |
| `alert_median_ack_seconds` | median of (acknowledged − created) | acknowledged alerts | Unacknowledged alerts are **excluded and counted** in `excluded_missing` |
| `alert_resolution_rate` | alerts with `status = resolved` | all alerts | Open alerts count only in the denominator |
| `high_priority_alert_count` | `severity IN (high, critical)` | *(a count)* | A CHECK constraint makes an unknown severity impossible |
| `checkin_completion_rate` | check-ins `taken` | check-ins `taken`/`missed`/`skipped` | Pending/cancelled excluded **and counted** |
| `medication_adherence_rate` | doses `taken` | doses `taken`/`missed`/`skipped` | Unlogged doses are invisible — measured among *logged* doses only |
| `care_plan_adherence_rate` | actionable items with a positive outcome | active, actionable items | `note` and `reminder` items excluded (nothing to measure against) |
| `model_metric_coverage` | finished runs with `metrics_json` | finished runs | Runs still pending/running excluded **and counted** |

### How the API reports them

```json
{
  "kpi_key": "alert_acknowledgement_rate",
  "unit": "ratio",
  "value": 0.5,
  "numerator": 1,
  "denominator": 2,
  "window_start": "2026-10-20T11:00:00+00:00",
  "window_end": "2026-10-20T13:00:00+00:00",
  "excluded_missing": 0,
  "is_measurable": true,
  "unmeasurable_reason": null
}
```

When there is not enough data:

```json
{
  "value": null,
  "is_measurable": false,
  "unmeasurable_reason": "No acknowledged alerts in this window, so no median can be computed. The count of unacknowledged alerts is reported in excluded_missing."
}
```

**`value: null` is the honest answer.** A ratio with an empty denominator is
undefined. Returning `0.0` would read as "everything failed" and `1.0` as
"everything passed" — both fabrications. The API returns neither.

---

## 6. What is *not* claimed

- These KPIs measure the **care workflow**, not the residents' health.
- `medication_adherence_rate` cannot detect a dose that was never logged.
- `high_priority_alert_count` is not a medical risk count.
- No KPI here reports model quality. Model precision/recall/F1 come from the
  model evaluation pipeline and are stored in `model_runs.metrics_json` only when
  actually measured. `model_metric_coverage` reports whether metrics *exist*, not
  whether they are good.
- The analytics SQL is syntax-verified, but has **not** been executed against a
  live PostgreSQL server yet. That is stated in `analytics/README.md`.
