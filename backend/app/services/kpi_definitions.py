"""Measurable KPIs for the alerting and care workflow.

Purpose
-------
Every KPI here is defined by *three things that must be written down together*:

1. **Numerator** — exactly which rows count.
2. **Denominator** — exactly which rows are eligible, i.e. what the KPI is "out
   of".
3. **Date range** — the window over which both are counted.
4. **Missing-data handling** — what happens when a needed value is absent.

That last one is where reporting usually lies. If we silently dropped rows with
missing acknowledgements, "median acknowledgement time" would look excellent
because the slowest alerts were the ones excluded. Here, missing values are
counted explicitly (`excluded_missing`) rather than hidden.

No KPI in this module is computed from invented numbers. If there is not enough
real data, the KPI is returned with `is_measurable = False` and a stated reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class KpiUnit(str, Enum):
    """How a KPI's value should be read."""

    RATIO = "ratio"  # 0..1
    PERCENT = "percent"  # 0..100
    COUNT = "count"
    SECONDS = "seconds"


@dataclass(frozen=True)
class KpiDefinition:
    """A KPI's formal definition, independent of any particular computation.

    `numerator_description` and `denominator_description` are the human-readable
    contract; the SQL in `analytics/sql/` must implement exactly these words.
    """

    key: str
    name: str
    numerator_description: str
    denominator_description: str
    unit: KpiUnit
    missing_data_handling: str
    notes: str = ""


# ---------------------------------------------------------------------------
# The KPI catalogue
# ---------------------------------------------------------------------------
# Grouped by theme. Each entry documents what the number means so the SQL views
# and the tests cannot drift from the definition.

ALERT_ACKNOWLEDGEMENT_RATE = KpiDefinition(
    key="alert_acknowledgement_rate",
    name="Alert acknowledgement rate",
    numerator_description=(
        "Alerts created in the window whose acknowledged_at is not null."
    ),
    denominator_description=(
        "All alerts created in the window, regardless of status."
    ),
    unit=KpiUnit.RATIO,
    missing_data_handling=(
        "Alerts with a null acknowledged_at count toward the denominator and "
        "not the numerator. They are never excluded, because excluding them "
        "would inflate the rate."
    ),
    notes="A dismissed alert still counts as acknowledged for this KPI if acknowledged_at is set.",
)

ALERT_MEDIAN_ACK_SECONDS = KpiDefinition(
    key="alert_median_ack_seconds",
    name="Median time to acknowledge an alert",
    numerator_description=(
        "For each acknowledged alert, the seconds between created_at and "
        "acknowledged_at; the median of those values."
    ),
    denominator_description=(
        "Alerts created in the window with a non-null acknowledged_at."
    ),
    unit=KpiUnit.SECONDS,
    missing_data_handling=(
        "Alerts with a null acknowledged_at are excluded from the median and "
        "reported separately as `excluded_missing`. The KPI also reports the "
        "excluded count so a high median cannot hide a large unacknowledged tail."
    ),
    notes="Median, not mean: a single very late acknowledgement should not distort the picture.",
)

ALERT_RESOLUTION_RATE = KpiDefinition(
    key="alert_resolution_rate",
    name="Alert resolution rate",
    numerator_description=(
        "Alerts created in the window whose status is 'resolved' (resolved_at not null)."
    ),
    denominator_description="All alerts created in the window.",
    unit=KpiUnit.RATIO,
    missing_data_handling=(
        "Unresolved alerts count in the denominator only. Alerts still open are "
        "not treated as failures — they may simply not have had time yet, which "
        "is why the date range must always accompany this number."
    ),
)

HIGH_PRIORITY_ALERT_COUNT = KpiDefinition(
    key="high_priority_alert_count",
    name="High-priority alert count",
    numerator_description=(
        "Alerts with severity in ('high', 'critical') created in the window."
    ),
    denominator_description="Not applicable — this is a count, not a ratio.",
    unit=KpiUnit.COUNT,
    missing_data_handling=(
        "No exclusion is needed: the alerts.severity CHECK constraint means "
        "only the five known severity levels can be stored, so an unrecognised "
        "value cannot enter the table and cannot skew this count."
    ),
    notes="Counts operational priority, which is not the same as validated medical risk.",
)

CHECKIN_COMPLETION_RATE = KpiDefinition(
    key="checkin_completion_rate",
    name="Check-in completion rate",
    numerator_description=(
        "Check-ins performed in the window whose status is 'taken'."
    ),
    denominator_description=(
        "Check-ins in the window whose status is one of "
        "('taken', 'missed', 'skipped') — that is, resolved outcomes."
    ),
    unit=KpiUnit.RATIO,
    missing_data_handling=(
        "Check-ins still in status 'scheduled' or 'cancelled' are excluded from "
        "both parts and reported as `excluded_pending`, because they are not yet "
        "a completed or failed outcome."
    ),
)

MEDICATION_ADHERENCE_RATE = KpiDefinition(
    key="medication_adherence_rate",
    name="Medication adherence rate",
    numerator_description=(
        "Medication dose logs in the window whose status is 'taken'."
    ),
    denominator_description=(
        "Medication dose logs in the window whose status is one of "
        "('taken', 'missed', 'skipped')."
    ),
    unit=KpiUnit.RATIO,
    missing_data_handling=(
        "Doses never logged at all cannot be counted and are therefore NOT "
        "included; this KPI measures adherence among *logged* doses and must "
        "always be read with the logged-dose count beside it. It cannot prove "
        "that an unlogged dose was not taken."
    ),
)

CARE_PLAN_ADHERENCE_RATE = KpiDefinition(
    key="care_plan_adherence_rate",
    name="Care-plan adherence rate",
    numerator_description=(
        "Active care-plan items in the window with at least one matching "
        "positive outcome (a taken dose or a taken check-in)."
    ),
    denominator_description=(
        "Active, actionable care-plan items (kind medication or checkin) "
        "belonging to active care plans whose period overlaps the window."
    ),
    unit=KpiUnit.RATIO,
    missing_data_handling=(
        "Plan items of kind 'note' are excluded from both parts: a note is "
        "documentation, not an action that can be adhered to. Items of kind "
        "'reminder' are also excluded, because reminders have no occurrence log "
        "yet and so cannot be measured."
    ),
)

MODEL_METRIC_COVERAGE = KpiDefinition(
    key="model_metric_coverage",
    name="Model-run metric coverage",
    numerator_description=(
        "Finished model runs in the window whose metrics_json is not null."
    ),
    denominator_description=(
        "Model runs in the window whose status is 'succeeded' or 'failed'."
    ),
    unit=KpiUnit.RATIO,
    missing_data_handling=(
        "Runs still 'pending' or 'running' are excluded from both parts. This "
        "KPI measures whether runs *record* metrics; it says nothing about "
        "whether those metrics are good."
    ),
    notes=(
        "This KPI deliberately reports only coverage/availability of metrics. "
        "Model quality metrics (precision/recall/F1) are produced by the model "
        "evaluation pipeline, never invented here."
    ),
)


ALL_KPIS: tuple[KpiDefinition, ...] = (
    ALERT_ACKNOWLEDGEMENT_RATE,
    ALERT_MEDIAN_ACK_SECONDS,
    ALERT_RESOLUTION_RATE,
    HIGH_PRIORITY_ALERT_COUNT,
    CHECKIN_COMPLETION_RATE,
    MEDICATION_ADHERENCE_RATE,
    CARE_PLAN_ADHERENCE_RATE,
    MODEL_METRIC_COVERAGE,
)


def get_kpi(key: str) -> KpiDefinition:
    """Look up a KPI definition by key."""
    for definition in ALL_KPIS:
        if definition.key == key:
            return definition
    raise KeyError(f"Unknown KPI: {key!r}")


@dataclass(frozen=True)
class KpiResult:
    """A computed KPI value with the provenance needed to trust it.

    `is_measurable` is False when the denominator is empty or too small to say
    anything. A KPI is never reported as a number when it cannot be measured.
    """

    key: str
    name: str
    unit: KpiUnit
    value: float | None
    numerator: int | None
    denominator: int | None
    window_start: datetime
    window_end: datetime
    excluded_missing: int
    is_measurable: bool
    unmeasurable_reason: str | None = None
    # A caveat about how missing data affects this particular value (for example
    # 'N alerts have no acknowledgement and therefore lower this rate'). Kept
    # separate from `unmeasurable_reason`, which explains why there is no value.
    missing_data_note: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Flat mapping for CSV export and JSON responses."""
        return {
            "kpi_key": self.key,
            "kpi_name": self.name,
            "unit": self.unit.value,
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "excluded_missing": self.excluded_missing,
            "is_measurable": self.is_measurable,
            "unmeasurable_reason": self.unmeasurable_reason,
            "missing_data_note": self.missing_data_note,
        }


def ratio_kpi(
    definition: KpiDefinition,
    *,
    numerator: int,
    denominator: int,
    window_start: datetime,
    window_end: datetime,
    excluded_missing: int = 0,
    minimum_denominator: int = 1,
    missing_data_note: str | None = None,
) -> KpiResult:
    """Compute a ratio-style KPI, refusing to invent a value when undefined.

    A ratio with a zero denominator is mathematically undefined. Returning
    `value = 0.0` there would read as "everything failed", and returning 1.0
    would read as "everything passed"; both would be fabrications. We return
    None and say why.
    """
    if denominator < minimum_denominator:
        return KpiResult(
            key=definition.key,
            name=definition.name,
            unit=definition.unit,
            value=None,
            numerator=numerator,
            denominator=denominator,
            window_start=window_start,
            window_end=window_end,
            excluded_missing=excluded_missing,
            is_measurable=False,
            unmeasurable_reason=(
                f"Denominator is {denominator}, below the minimum of "
                f"{minimum_denominator}. No value can be reported from this window."
            ),
            missing_data_note=missing_data_note,
        )

    raw = numerator / denominator
    value = raw * 100.0 if definition.unit is KpiUnit.PERCENT else raw
    return KpiResult(
        key=definition.key,
        name=definition.name,
        unit=definition.unit,
        value=value,
        numerator=numerator,
        denominator=denominator,
        window_start=window_start,
        window_end=window_end,
        excluded_missing=excluded_missing,
        is_measurable=True,
        missing_data_note=missing_data_note,
    )


def count_kpi(
    definition: KpiDefinition,
    *,
    count: int,
    window_start: datetime,
    window_end: datetime,
    excluded_missing: int = 0,
) -> KpiResult:
    """Compute a count-style KPI (always measurable, even when it is zero)."""
    return KpiResult(
        key=definition.key,
        name=definition.name,
        unit=definition.unit,
        value=float(count),
        numerator=count,
        denominator=None,
        window_start=window_start,
        window_end=window_end,
        excluded_missing=excluded_missing,
        is_measurable=True,
    )
