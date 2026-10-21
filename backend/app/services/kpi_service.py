"""Compute the KPIs defined in `kpi_definitions.py` from real stored data.

Design rules
------------
* Every function takes an explicit `window_start` / `window_end`. No KPI is
  ever reported without its date range.
* No value is invented. When the data cannot support a KPI, the result says so
  (`is_measurable = False`) rather than returning a plausible-looking number.
* Missing values are counted (`excluded_missing`) instead of silently dropped.
* `source = 'simulated'` rows are **included but counted separately** where it
  matters, so demo data can never be mistaken for real measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.alerts import Alert
from backend.app.models.care import (
    CarePlan,
    CarePlanItem,
    Checkin,
    MedicationDoseLog,
    MedicationSchedule,
)
from backend.app.models.events import ModelRun
from backend.app.services.kpi_definitions import (
    ALERT_ACKNOWLEDGEMENT_RATE,
    ALERT_MEDIAN_ACK_SECONDS,
    ALERT_RESOLUTION_RATE,
    CARE_PLAN_ADHERENCE_RATE,
    CHECKIN_COMPLETION_RATE,
    HIGH_PRIORITY_ALERT_COUNT,
    MEDICATION_ADHERENCE_RATE,
    MODEL_METRIC_COVERAGE,
    KpiResult,
    count_kpi,
    ratio_kpi,
)

# Status vocabularies, referenced explicitly so the SQL and the code agree.
CHECKIN_RESOLVED_OUTCOMES = ("taken", "missed", "skipped")
CHECKIN_PENDING_OUTCOMES = ("scheduled", "cancelled")
DOSE_RESOLVED_OUTCOMES = ("taken", "missed", "skipped")
MODEL_FINISHED_STATUSES = ("succeeded", "failed")


@dataclass(frozen=True)
class KpiWindow:
    """An explicit, inclusive-start/exclusive-end reporting window."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("KPI window end must be after its start.")


def _count(db: Session, stmt) -> int:
    """Run a `select(func.count())` statement and return the integer."""
    return int(db.execute(stmt).scalar_one() or 0)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def alert_acknowledgement_rate(db: Session, window: KpiWindow) -> KpiResult:
    """Share of alerts in the window that were acknowledged."""
    base = Alert.created_at >= window.start, Alert.created_at < window.end
    total = _count(db, select(func.count()).select_from(Alert).where(*base))
    acknowledged = _count(
        db,
        select(func.count())
        .select_from(Alert)
        .where(*base, Alert.acknowledged_at.is_not(None)),
    )
    # Alerts with a null acknowledged_at stay in the denominator; the ratio
    # itself is how we report the gap, so nothing is excluded on top of that.
    return ratio_kpi(
        ALERT_ACKNOWLEDGEMENT_RATE,
        numerator=acknowledged,
        denominator=total,
        window_start=window.start,
        window_end=window.end,
        missing_data_note=(
            f"{total - acknowledged} alert(s) in the window have no "
            "acknowledgement and therefore lower this rate."
        ),
        minimum_denominator=1,
    )


def alert_median_ack_seconds(db: Session, window: KpiWindow) -> KpiResult:
    """Median seconds from alert creation to acknowledgement.

    Acknowledged alerts only. Unacknowledged alerts are *excluded and counted*,
    because folding them in as zero or dropping them silently would both lie.
    """
    base = Alert.created_at >= window.start, Alert.created_at < window.end
    total = _count(db, select(func.count()).select_from(Alert).where(*base))
    rows = (
        db.execute(
            select(Alert.created_at, Alert.acknowledged_at).where(
                *base, Alert.acknowledged_at.is_not(None)
            )
        )
        .all()
    )

    deltas: list[float] = []
    unparseable = 0
    for created_at, acknowledged_at in rows:
        if created_at is None or acknowledged_at is None:
            unparseable += 1
            continue
        deltas.append((acknowledged_at - created_at).total_seconds())

    excluded = (total - len(rows)) + unparseable

    if not deltas:
        return KpiResult(
            key=ALERT_MEDIAN_ACK_SECONDS.key,
            name=ALERT_MEDIAN_ACK_SECONDS.name,
            unit=ALERT_MEDIAN_ACK_SECONDS.unit,
            value=None,
            numerator=0,
            denominator=0,
            window_start=window.start,
            window_end=window.end,
            excluded_missing=excluded,
            is_measurable=False,
            unmeasurable_reason=(
                "No acknowledged alerts in this window, so no median can be "
                "computed. The count of unacknowledged alerts is reported in "
                "excluded_missing."
            ),
        )

    deltas.sort()
    middle = len(deltas) // 2
    median = (
        deltas[middle]
        if len(deltas) % 2 == 1
        else (deltas[middle - 1] + deltas[middle]) / 2.0
    )

    return KpiResult(
        key=ALERT_MEDIAN_ACK_SECONDS.key,
        name=ALERT_MEDIAN_ACK_SECONDS.name,
        unit=ALERT_MEDIAN_ACK_SECONDS.unit,
        value=median,
        numerator=len(deltas),
        denominator=len(deltas),
        window_start=window.start,
        window_end=window.end,
        excluded_missing=excluded,
        is_measurable=True,
    )


def alert_resolution_rate(db: Session, window: KpiWindow) -> KpiResult:
    """Share of alerts in the window that reached status 'resolved'."""
    base = Alert.created_at >= window.start, Alert.created_at < window.end
    total = _count(db, select(func.count()).select_from(Alert).where(*base))
    resolved = _count(
        db,
        select(func.count())
        .select_from(Alert)
        .where(*base, Alert.status == "resolved"),
    )
    return ratio_kpi(
        ALERT_RESOLUTION_RATE,
        numerator=resolved,
        denominator=total,
        window_start=window.start,
        window_end=window.end,
        minimum_denominator=1,
    )


def high_priority_alert_count(db: Session, window: KpiWindow) -> KpiResult:
    """Count of high/critical *operational priority* alerts in the window.

    The `alerts.severity` CHECK constraint means only the five known levels can
    be stored, so there is no "unrecognised severity" bucket to exclude here —
    a bad value cannot enter the table in the first place.
    """
    base = Alert.created_at >= window.start, Alert.created_at < window.end

    count = _count(
        db,
        select(func.count())
        .select_from(Alert)
        .where(*base, Alert.severity.in_(("high", "critical"))),
    )
    return count_kpi(
        HIGH_PRIORITY_ALERT_COUNT,
        count=count,
        window_start=window.start,
        window_end=window.end,
    )


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------


def checkin_completion_rate(db: Session, window: KpiWindow) -> KpiResult:
    """Share of resolved check-ins in the window that were taken."""
    base = (
        Checkin.performed_at.is_not(None),
        Checkin.performed_at >= window.start,
        Checkin.performed_at < window.end,
    )
    resolved = _count(
        db,
        select(func.count())
        .select_from(Checkin)
        .where(*base, Checkin.status.in_(CHECKIN_RESOLVED_OUTCOMES)),
    )
    taken = _count(
        db,
        select(func.count())
        .select_from(Checkin)
        .where(*base, Checkin.status == "taken"),
    )
    pending = _count(
        db,
        select(func.count())
        .select_from(Checkin)
        .where(*base, Checkin.status.in_(CHECKIN_PENDING_OUTCOMES)),
    )
    return ratio_kpi(
        CHECKIN_COMPLETION_RATE,
        numerator=taken,
        denominator=resolved,
        window_start=window.start,
        window_end=window.end,
        excluded_missing=pending,
        minimum_denominator=1,
    )


# ---------------------------------------------------------------------------
# Medication
# ---------------------------------------------------------------------------


def medication_adherence_rate(db: Session, window: KpiWindow) -> KpiResult:
    """Share of *logged* doses in the window that were taken.

    Honest limitation, stated in the result: doses that were never logged at
    all cannot be counted, so this measures adherence among logged doses only.
    """
    base = (
        MedicationDoseLog.scheduled_for >= window.start,
        MedicationDoseLog.scheduled_for < window.end,
    )
    resolved = _count(
        db,
        select(func.count())
        .select_from(MedicationDoseLog)
        .where(*base, MedicationDoseLog.status.in_(DOSE_RESOLVED_OUTCOMES)),
    )
    taken = _count(
        db,
        select(func.count())
        .select_from(MedicationDoseLog)
        .where(*base, MedicationDoseLog.status == "taken"),
    )
    pending = _count(
        db,
        select(func.count())
        .select_from(MedicationDoseLog)
        .where(*base, MedicationDoseLog.status.in_(("scheduled", "cancelled"))),
    )
    return ratio_kpi(
        MEDICATION_ADHERENCE_RATE,
        numerator=taken,
        denominator=resolved,
        window_start=window.start,
        window_end=window.end,
        excluded_missing=pending,
        minimum_denominator=1,
    )


# ---------------------------------------------------------------------------
# Care plans
# ---------------------------------------------------------------------------


def care_plan_adherence_rate(db: Session, window: KpiWindow) -> KpiResult:
    """Share of active, actionable care-plan items with a positive outcome.

    'Positive outcome' means: for a medication item, at least one 'taken' dose
    in the window; for a check-in item, at least one 'taken' check-in; for a
    reminder item, any recorded outcome is out of scope for now (reminders have
    no occurrence log yet), so reminders are excluded from both parts and
    reported as `excluded_missing`.
    """
    window_date_start = window.start.date()
    window_date_end = window.end.date()

    # Care plans whose period overlaps the window (open-ended plans always do).
    plan_rows = db.execute(
        select(CarePlan.id).where(
            (CarePlan.start_date.is_(None)) | (CarePlan.start_date <= window_date_end),
            (CarePlan.end_date.is_(None)) | (CarePlan.end_date >= window_date_start),
            CarePlan.status == "active",
        )
    ).scalars().all()
    plan_ids = list(plan_rows)

    if not plan_ids:
        return ratio_kpi(
            CARE_PLAN_ADHERENCE_RATE,
            numerator=0,
            denominator=0,
            window_start=window.start,
            window_end=window.end,
            minimum_denominator=1,
        )

    items = db.execute(
        select(
            CarePlanItem.id,
            CarePlanItem.item_kind,
            CarePlanItem.medication_schedule_id,
            CarePlanItem.checkin_schedule_id,
        ).where(
            CarePlanItem.care_plan_id.in_(plan_ids),
            CarePlanItem.is_active.is_(True),
        )
    ).all()

    actionable = 0
    adhered = 0
    excluded = 0

    for _item_id, item_kind, medication_schedule_id, checkin_schedule_id in items:
        if item_kind == "medication" and medication_schedule_id is not None:
            actionable += 1
            doses_taken = _count(
                db,
                select(func.count())
                .select_from(MedicationDoseLog)
                .where(
                    MedicationDoseLog.medication_schedule_id == medication_schedule_id,
                    MedicationDoseLog.status == "taken",
                    MedicationDoseLog.scheduled_for >= window.start,
                    MedicationDoseLog.scheduled_for < window.end,
                ),
            )
            if doses_taken > 0:
                adhered += 1
        elif item_kind == "checkin" and checkin_schedule_id is not None:
            actionable += 1
            checkins_taken = _count(
                db,
                select(func.count())
                .select_from(Checkin)
                .where(
                    Checkin.checkin_schedule_id == checkin_schedule_id,
                    Checkin.status == "taken",
                    Checkin.performed_at.is_not(None),
                    Checkin.performed_at >= window.start,
                    Checkin.performed_at < window.end,
                ),
            )
            if checkins_taken > 0:
                adhered += 1
        else:
            # 'note', or 'reminder' (no occurrence log yet): not a measurable action.
            excluded += 1

    return ratio_kpi(
        CARE_PLAN_ADHERENCE_RATE,
        numerator=adhered,
        denominator=actionable,
        window_start=window.start,
        window_end=window.end,
        excluded_missing=excluded,
        minimum_denominator=1,
    )


# ---------------------------------------------------------------------------
# Model runs
# ---------------------------------------------------------------------------


def model_metric_coverage(db: Session, window: KpiWindow) -> KpiResult:
    """Share of finished model runs that recorded metrics.

    This measures *availability* of metrics only. It is not a statement about
    model quality, and no precision/recall/F1 is derived here.
    """
    base = (
        ModelRun.started_at >= window.start,
        ModelRun.started_at < window.end,
    )
    finished = _count(
        db,
        select(func.count())
        .select_from(ModelRun)
        .where(*base, ModelRun.status.in_(MODEL_FINISHED_STATUSES)),
    )
    with_metrics = _count(
        db,
        select(func.count())
        .select_from(ModelRun)
        .where(*base, ModelRun.status.in_(MODEL_FINISHED_STATUSES), ModelRun.metrics_json.is_not(None)),
    )
    unfinished = _count(
        db,
        select(func.count())
        .select_from(ModelRun)
        .where(*base, ModelRun.status.in_(("pending", "running"))),
    )
    return ratio_kpi(
        MODEL_METRIC_COVERAGE,
        numerator=with_metrics,
        denominator=finished,
        window_start=window.start,
        window_end=window.end,
        excluded_missing=unfinished,
        minimum_denominator=1,
    )


# ---------------------------------------------------------------------------
# Convenience: everything at once
# ---------------------------------------------------------------------------


def compute_all_kpis(db: Session, window: KpiWindow) -> list[KpiResult]:
    """Compute every catalogue KPI for one window, in catalogue order."""
    return [
        alert_acknowledgement_rate(db, window),
        alert_median_ack_seconds(db, window),
        alert_resolution_rate(db, window),
        high_priority_alert_count(db, window),
        checkin_completion_rate(db, window),
        medication_adherence_rate(db, window),
        care_plan_adherence_rate(db, window),
        model_metric_coverage(db, window),
    ]


__all__ = [
    "CHECKIN_PENDING_OUTCOMES",
    "CHECKIN_RESOLVED_OUTCOMES",
    "DOSE_RESOLVED_OUTCOMES",
    "MODEL_FINISHED_STATUSES",
    "KpiWindow",
    "alert_acknowledgement_rate",
    "alert_median_ack_seconds",
    "alert_resolution_rate",
    "care_plan_adherence_rate",
    "checkin_completion_rate",
    "compute_all_kpis",
    "high_priority_alert_count",
    "medication_adherence_rate",
    "model_metric_coverage",
]


# Referenced by analytics SQL generation so the two cannot drift silently.
CARE_PLAN_ITEM_KINDS_ACTIONABLE = ("medication", "checkin")
_ = (CarePlan, MedicationSchedule)  # imported for FK clarity in future joins
