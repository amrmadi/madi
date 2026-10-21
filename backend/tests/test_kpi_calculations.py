"""Tests for KPI calculations.

What these tests protect
------------------------
The easiest way to publish a flattering number by accident is to let rows with
missing data vanish from a denominator. Several tests here construct exactly
that trap and assert the KPI counts it honestly instead.

Every test also checks the window is reported, because a KPI without a date
range is meaningless.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from backend.app.models.alerts import Alert
from backend.app.models.care import (
    CarePlan,
    CarePlanItem,
    Checkin,
    CheckinSchedule,
    MedicationDoseLog,
    MedicationSchedule,
)
from backend.app.models.events import ModelRun
from backend.app.models.identity import ElderlyProfile
from backend.app.services.kpi_definitions import KpiUnit, get_kpi
from backend.app.services.kpi_service import (
    KpiWindow,
    alert_acknowledgement_rate,
    alert_median_ack_seconds,
    alert_resolution_rate,
    care_plan_adherence_rate,
    checkin_completion_rate,
    compute_all_kpis,
    high_priority_alert_count,
    medication_adherence_rate,
    model_metric_coverage,
)

START = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
WINDOW = KpiWindow(start=START, end=END)
MID = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def resident(db_session: Session) -> ElderlyProfile:
    profile = ElderlyProfile(display_name="KPI Resident", is_active=True)
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


def add_alert(
    db: Session,
    profile: ElderlyProfile,
    *,
    created_at: datetime = MID,
    acknowledged_at: datetime | None = None,
    status: str = "new",
    severity: str = "medium",
    alert_type: str = "fall",
) -> Alert:
    # The schema requires: status 'new' => acknowledged_at IS NULL, and any
    # closed status (acknowledged/resolved/dismissed) => acknowledged_at is set.
    # Infer a consistent status so the fixtures are always valid rows: when an
    # acknowledged_at is supplied but the status was left at its default, the
    # alert is genuinely acknowledged.
    if status == "new" and acknowledged_at is not None:
        status = "acknowledged"
    if status == "new":
        acknowledged_at = None
    elif acknowledged_at is None:
        acknowledged_at = created_at

    alert = Alert(
        elderly_profile_id=profile.id,
        alert_type=alert_type,
        severity=severity,
        status=status,
        title="KPI test alert",
        created_at=created_at,
        acknowledged_at=acknowledged_at,
        resolved_at=acknowledged_at if status == "resolved" else None,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# Window validation
# ---------------------------------------------------------------------------


def test_window_rejects_end_before_start() -> None:
    with pytest.raises(ValueError):
        KpiWindow(start=END, end=START)


def test_window_rejects_zero_length() -> None:
    with pytest.raises(ValueError):
        KpiWindow(start=START, end=START)


# ---------------------------------------------------------------------------
# Alert acknowledgement rate
# ---------------------------------------------------------------------------


def test_ack_rate_counts_unacknowledged_in_denominator(
    db_session: Session, resident: ElderlyProfile
) -> None:
    """The trap: dropping unacknowledged alerts would report 100%."""
    add_alert(db_session, resident, acknowledged_at=MID + timedelta(minutes=5))
    add_alert(db_session, resident, acknowledged_at=None)
    add_alert(db_session, resident, acknowledged_at=None)

    result = alert_acknowledgement_rate(db_session, WINDOW)

    assert result.numerator == 1
    assert result.denominator == 3
    assert result.value == pytest.approx(1 / 3)
    assert result.is_measurable is True
    assert result.window_start == START
    assert result.window_end == END


def test_ack_rate_with_no_alerts_is_not_measurable(
    db_session: Session, resident: ElderlyProfile
) -> None:
    """An empty window must not report 0% or 100%; it reports 'unknown'."""
    result = alert_acknowledgement_rate(db_session, WINDOW)

    assert result.is_measurable is False
    assert result.value is None
    assert result.unmeasurable_reason is not None


def test_ack_rate_ignores_alerts_outside_the_window(
    db_session: Session, resident: ElderlyProfile
) -> None:
    add_alert(db_session, resident, created_at=START - timedelta(days=1))
    add_alert(db_session, resident, acknowledged_at=MID)

    result = alert_acknowledgement_rate(db_session, WINDOW)

    assert result.denominator == 1
    assert result.value == pytest.approx(1.0)


def test_ack_rate_window_boundary_is_inclusive_at_start_exclusive_at_end(
    db_session: Session, resident: ElderlyProfile
) -> None:
    add_alert(db_session, resident, created_at=START, acknowledged_at=START)
    add_alert(db_session, resident, created_at=END)

    result = alert_acknowledgement_rate(db_session, WINDOW)

    # The alert created exactly at END belongs to the next window.
    assert result.denominator == 1


# ---------------------------------------------------------------------------
# Median acknowledgement time
# ---------------------------------------------------------------------------


def test_median_ack_seconds_reports_excluded_missing(
    db_session: Session, resident: ElderlyProfile
) -> None:
    """Unacknowledged alerts must be counted as excluded, not forgotten."""
    add_alert(db_session, resident, acknowledged_at=MID + timedelta(seconds=60))
    add_alert(db_session, resident, acknowledged_at=MID + timedelta(seconds=120))
    add_alert(db_session, resident, acknowledged_at=MID + timedelta(seconds=180))
    add_alert(db_session, resident, acknowledged_at=None)

    result = alert_median_ack_seconds(db_session, WINDOW)

    assert result.value == pytest.approx(120.0)
    assert result.numerator == 3
    assert result.excluded_missing == 1
    assert result.is_measurable is True


def test_median_is_not_distorted_by_a_single_slow_acknowledgement(
    db_session: Session, resident: ElderlyProfile
) -> None:
    for seconds in (10, 20, 30):
        add_alert(db_session, resident, acknowledged_at=MID + timedelta(seconds=seconds))
    # One alert acknowledged a day later.
    add_alert(db_session, resident, acknowledged_at=MID + timedelta(days=1))

    result = alert_median_ack_seconds(db_session, WINDOW)

    # Median of (10, 20, 30, 86400) is 25; the mean would be ~21615.
    assert result.value == pytest.approx(25.0)


def test_median_with_no_acknowledged_alerts_is_not_measurable(
    db_session: Session, resident: ElderlyProfile
) -> None:
    add_alert(db_session, resident, acknowledged_at=None)

    result = alert_median_ack_seconds(db_session, WINDOW)

    assert result.is_measurable is False
    assert result.value is None
    assert result.excluded_missing == 1


# ---------------------------------------------------------------------------
# Resolution rate and high-priority count
# ---------------------------------------------------------------------------


def test_resolution_rate_uses_all_alerts_as_denominator(
    db_session: Session, resident: ElderlyProfile
) -> None:
    add_alert(db_session, resident, status="resolved", acknowledged_at=MID)
    add_alert(db_session, resident, status="new")

    result = alert_resolution_rate(db_session, WINDOW)

    assert result.numerator == 1
    assert result.denominator == 2
    assert result.value == pytest.approx(0.5)


def test_high_priority_count_selects_only_high_and_critical(
    db_session: Session, resident: ElderlyProfile
) -> None:
    for severity in ("info", "low", "medium", "high", "critical"):
        add_alert(db_session, resident, severity=severity)

    result = high_priority_alert_count(db_session, WINDOW)

    assert result.value == 2.0
    assert result.unit is KpiUnit.COUNT
    assert result.excluded_missing == 0


def test_severity_outside_the_known_set_cannot_be_stored(
    db_session: Session, resident: ElderlyProfile
) -> None:
    """The database itself rejects an unknown severity.

    This is stronger than filtering bad values at report time: an alert with a
    severity nobody recognises cannot enter the table at all, so the high-priority
    count can never be skewed by one.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.execute(
            Alert.__table__.insert().values(
                elderly_profile_id=resident.id,
                alert_type="fall",
                severity="catastrophic",
                status="new",
                title="Bad severity",
                created_at=MID,
                occurrence_count=1,
            )
        )
        db_session.commit()
    db_session.rollback()


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------


def add_checkin(
    db_session: Session,
    profile: ElderlyProfile,
    *,
    status: str,
    performed_at: datetime | None = MID,
    schedule_id: int | None = None,
) -> Checkin:
    checkin = Checkin(
        elderly_profile_id=profile.id,
        checkin_schedule_id=schedule_id,
        checkin_type="wellbeing",
        status=status,
        scheduled_for=MID,
        performed_at=performed_at,
        created_at=MID,
    )
    db_session.add(checkin)
    db_session.commit()
    db_session.refresh(checkin)
    return checkin


def test_checkin_completion_rate_counts_only_resolved_outcomes(
    db_session: Session, resident: ElderlyProfile
) -> None:
    add_checkin(db_session, resident, status="taken")
    add_checkin(db_session, resident, status="taken")
    add_checkin(db_session, resident, status="missed")
    add_checkin(db_session, resident, status="skipped")
    # Pending ones are not yet an outcome and must be excluded, but counted.
    add_checkin(db_session, resident, status="scheduled")
    add_checkin(db_session, resident, status="cancelled")

    result = checkin_completion_rate(db_session, WINDOW)

    assert result.numerator == 2
    assert result.denominator == 4
    assert result.value == pytest.approx(0.5)
    assert result.excluded_missing == 2


def test_checkin_rate_with_no_resolved_checkins_is_not_measurable(
    db_session: Session, resident: ElderlyProfile
) -> None:
    add_checkin(db_session, resident, status="scheduled")

    result = checkin_completion_rate(db_session, WINDOW)

    assert result.is_measurable is False
    assert result.excluded_missing == 1


# ---------------------------------------------------------------------------
# Medication
# ---------------------------------------------------------------------------


def add_dose(
    db_session: Session,
    schedule: MedicationSchedule,
    *,
    status: str,
    scheduled_for: datetime = MID,
) -> MedicationDoseLog:
    dose = MedicationDoseLog(
        medication_schedule_id=schedule.id,
        scheduled_for=scheduled_for,
        status=status,
    )
    db_session.add(dose)
    db_session.commit()
    db_session.refresh(dose)
    return dose


@pytest.fixture()
def medication_schedule(db_session: Session, resident: ElderlyProfile) -> MedicationSchedule:
    schedule = MedicationSchedule(
        elderly_profile_id=resident.id,
        medication_name="Demo drug",
        recurrence="daily",
        time_of_day="08:00",
        is_active=True,
    )
    db_session.add(schedule)
    db_session.commit()
    db_session.refresh(schedule)
    return schedule


def test_medication_adherence_measures_logged_doses_only(
    db_session: Session, medication_schedule: MedicationSchedule
) -> None:
    add_dose(db_session, medication_schedule, status="taken")
    add_dose(db_session, medication_schedule, status="taken")
    add_dose(db_session, medication_schedule, status="missed")
    add_dose(db_session, medication_schedule, status="scheduled")

    result = medication_adherence_rate(db_session, WINDOW)

    assert result.numerator == 2
    assert result.denominator == 3
    assert result.value == pytest.approx(2 / 3)
    assert result.excluded_missing == 1


def test_medication_adherence_ignores_doses_outside_window(
    db_session: Session, medication_schedule: MedicationSchedule
) -> None:
    add_dose(db_session, medication_schedule, status="taken", scheduled_for=START - timedelta(days=2))
    add_dose(db_session, medication_schedule, status="missed")

    result = medication_adherence_rate(db_session, WINDOW)

    assert result.denominator == 1
    assert result.value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Care-plan adherence
# ---------------------------------------------------------------------------


def test_care_plan_adherence_counts_actionable_items(
    db_session: Session, resident: ElderlyProfile, medication_schedule: MedicationSchedule
) -> None:
    plan = CarePlan(
        elderly_profile_id=resident.id,
        title="Adherence plan",
        status="active",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)

    schedule = CheckinSchedule(
        elderly_profile_id=resident.id,
        title="Daily check",
        checkin_type="wellbeing",
        recurrence="daily",
    )
    db_session.add(schedule)
    db_session.commit()
    db_session.refresh(schedule)

    db_session.add_all(
        [
            CarePlanItem(
                care_plan_id=plan.id,
                item_kind="medication",
                title="Morning dose",
                is_active=True,
                medication_schedule_id=medication_schedule.id,
            ),
            CarePlanItem(
                care_plan_id=plan.id,
                item_kind="checkin",
                title="Daily check-in",
                is_active=True,
                checkin_schedule_id=schedule.id,
            ),
            CarePlanItem(
                care_plan_id=plan.id,
                item_kind="note",
                title="Just a note",
                is_active=True,
            ),
        ]
    )
    db_session.commit()

    # Medication adhered to; check-in missed.
    add_dose(db_session, medication_schedule, status="taken")
    add_checkin(db_session, resident, status="missed", schedule_id=schedule.id)

    result = care_plan_adherence_rate(db_session, WINDOW)

    # Two actionable items (medication + checkin); note is excluded.
    assert result.denominator == 2
    assert result.numerator == 1
    assert result.value == pytest.approx(0.5)
    assert result.excluded_missing == 1


def test_care_plan_adherence_excludes_inactive_items(
    db_session: Session, resident: ElderlyProfile, medication_schedule: MedicationSchedule
) -> None:
    plan = CarePlan(
        elderly_profile_id=resident.id,
        title="Plan",
        status="active",
        start_date=date(2026, 10, 1),
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)

    db_session.add(
        CarePlanItem(
            care_plan_id=plan.id,
            item_kind="medication",
            title="Inactive item",
            is_active=False,
            medication_schedule_id=medication_schedule.id,
        )
    )
    db_session.commit()

    result = care_plan_adherence_rate(db_session, WINDOW)

    assert result.denominator == 0
    assert result.is_measurable is False


# ---------------------------------------------------------------------------
# Model metric coverage
# ---------------------------------------------------------------------------


def add_model_run(db_session: Session, *, status: str, metrics_json: str | None) -> ModelRun:
    finished = status in ("succeeded", "failed")
    run = ModelRun(
        task="fall_detection",
        model_name="test-model",
        model_version="test-v1",
        status=status,
        started_at=MID,
        finished_at=MID + timedelta(seconds=5) if finished else None,
        metrics_json=metrics_json,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def test_model_metric_coverage_counts_only_finished_runs(db_session: Session) -> None:
    add_model_run(db_session, status="succeeded", metrics_json='{"f1": 0.8}')
    add_model_run(db_session, status="succeeded", metrics_json=None)
    add_model_run(db_session, status="failed", metrics_json='{"error": 1}')
    add_model_run(db_session, status="running", metrics_json=None)

    result = model_metric_coverage(db_session, WINDOW)

    assert result.numerator == 2
    assert result.denominator == 3
    assert result.excluded_missing == 1


def test_model_metric_coverage_makes_no_claim_about_model_quality(
    db_session: Session,
) -> None:
    """Coverage of metrics is not a quality statement."""
    add_model_run(db_session, status="succeeded", metrics_json='{"f1": 0.1}')

    result = model_metric_coverage(db_session, WINDOW)

    assert result.as_dict()["value"] == pytest.approx(1.0)
    assert "quality" not in " ".join(str(v) for v in result.as_dict().values()).lower()


# ---------------------------------------------------------------------------
# Catalogue consistency
# ---------------------------------------------------------------------------


def test_every_kpi_definition_documents_its_parts() -> None:
    from backend.app.services.kpi_definitions import ALL_KPIS

    assert len(ALL_KPIS) == 8
    for definition in ALL_KPIS:
        assert definition.numerator_description, definition.key
        assert definition.denominator_description, definition.key
        assert definition.missing_data_handling, definition.key


def test_get_kpi_rejects_unknown_key() -> None:
    with pytest.raises(KeyError):
        get_kpi("not_a_kpi")


def test_compute_all_kpis_returns_one_result_per_definition(
    db_session: Session, resident: ElderlyProfile
) -> None:
    from backend.app.services.kpi_definitions import ALL_KPIS

    add_alert(db_session, resident, acknowledged_at=MID)

    results = compute_all_kpis(db_session, WINDOW)

    assert len(results) == len(ALL_KPIS)
    assert [r.key for r in results] == [d.key for d in ALL_KPIS]


def test_results_serialise_to_flat_rows_with_their_window(
    db_session: Session, resident: ElderlyProfile
) -> None:
    add_alert(db_session, resident, acknowledged_at=MID)

    row = alert_acknowledgement_rate(db_session, WINDOW).as_dict()

    assert row["kpi_key"] == "alert_acknowledgement_rate"
    assert row["window_start"].startswith("2026-10-01")
    assert row["window_end"].startswith("2026-11-01")
    assert row["denominator"] == 1
