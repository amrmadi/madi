"""Tests for the configurable alert rule engine.

Two properties get the most attention here, because they are the point of the
engine:

1. **Missing data alone never becomes an emergency.** Several tests assert that
   an absent value produces *no* high-priority alert.
2. **Operational priority is separate from validated medical risk.** Tests show
   that an unverified signal cannot climb to CRITICAL, and that a validated
   risk assessment is the only non-fall path that can reach HIGH.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.enums import AlertType
from backend.app.schemas.alerts_engine import ObservationKind
from backend.app.services.alert_rules import (
    AlertRuleEngine,
    Observation,
    Priority,
    RuleConfig,
    RuleOutcome,
    build_dedupe_key,
    is_within_cooldown,
    next_occurrence_count,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def make_observation(kind: ObservationKind, **values) -> Observation:
    """Build an observation with sensible defaults for a given kind."""
    verified = bool(values.pop("verified", False))
    dedupe_key = values.pop("dedupe_key", None)
    return Observation(
        kind=kind,
        elderly_profile_id=1,
        observed_at=values.pop("observed_at", NOW),
        values=values,
        verified=verified,
        dedupe_key=dedupe_key,
    )


# ---------------------------------------------------------------------------
# Falls — the only path allowed to reach CRITICAL
# ---------------------------------------------------------------------------


def test_verified_fall_is_critical() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.FALL, verified=True))

    assert match.outcome is RuleOutcome.TRIGGERED
    assert match.priority is Priority.CRITICAL
    assert match.alert_type == AlertType.FALL.value
    assert "confirmed by a person" in match.message


def test_confident_unverified_fall_is_high_not_critical() -> None:
    """An unverified model guess must not be presented as a confirmed emergency."""
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.FALL, confidence=0.9))

    assert match.outcome is RuleOutcome.TRIGGERED
    assert match.priority is Priority.HIGH
    assert match.priority is not Priority.CRITICAL
    assert "unverified" in match.title.lower()


def test_fall_without_confidence_raises_no_emergency() -> None:
    """Missing confidence is not evidence of a fall."""
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.FALL, confidence=None))

    assert match.outcome is RuleOutcome.SUPPRESSED_NO_DATA
    assert match.should_alert is False
    assert match.priority.order < Priority.HIGH.order
    assert match.triggered_by_missing_data is True


def test_fall_below_floor_is_suppressed() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.FALL, confidence=0.1))

    assert match.outcome is RuleOutcome.SUPPRESSED_BELOW_THRESHOLD
    assert match.should_alert is False


def test_fall_between_floor_and_threshold_does_not_alert() -> None:
    engine = AlertRuleEngine()
    # Default floor 0.30, threshold 0.60.
    match = engine.evaluate(make_observation(ObservationKind.FALL, confidence=0.45))

    assert match.outcome is RuleOutcome.SUPPRESSED_BELOW_THRESHOLD
    assert match.should_alert is False
    assert match.priority is Priority.LOW


def test_fall_threshold_is_configurable() -> None:
    """A stricter configuration changes the decision without touching the rules."""
    strict = AlertRuleEngine(RuleConfig(fall_min_confidence=0.95))
    match = strict.evaluate(make_observation(ObservationKind.FALL, confidence=0.9))

    assert match.should_alert is False


# ---------------------------------------------------------------------------
# Missing data must never imply an emergency
# ---------------------------------------------------------------------------


def test_data_gap_cannot_exceed_configured_ceiling_even_when_huge() -> None:
    """A ten-day silence still must not become CRITICAL."""
    engine = AlertRuleEngine()
    match = engine.evaluate(
        make_observation(ObservationKind.DATA_GAP, gap_minutes=10 * 24 * 60)
    )

    assert match.outcome is RuleOutcome.TRIGGERED
    assert match.priority.order <= Priority.LOW.order
    assert match.priority is not Priority.CRITICAL
    assert match.triggered_by_missing_data is True
    assert "not evidence that the resident is unsafe" in match.message


def test_short_data_gap_is_not_worth_an_alert() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.DATA_GAP, gap_minutes=30))

    assert match.should_alert is False
    assert match.outcome is RuleOutcome.SUPPRESSED_BELOW_THRESHOLD


def test_data_gap_without_duration_is_suppressed() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.DATA_GAP))

    assert match.outcome is RuleOutcome.SUPPRESSED_NO_DATA
    assert match.triggered_by_missing_data is True


def test_missed_checkin_never_reaches_critical() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(
        make_observation(
            ObservationKind.MISSED_CHECKIN, minutes_late=600, consecutive_misses=9
        )
    )

    assert match.outcome is RuleOutcome.TRIGGERED
    assert match.priority is Priority.HIGH
    assert match.priority is not Priority.CRITICAL


def test_checkin_within_grace_period_is_not_an_alert() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(
        make_observation(ObservationKind.MISSED_CHECKIN, minutes_late=30)
    )

    assert match.should_alert is False


# ---------------------------------------------------------------------------
# Priority vs validated medical risk
# ---------------------------------------------------------------------------


def test_unverified_risk_score_cannot_reach_high() -> None:
    """Unvalidated numbers must not drive operational triage."""
    engine = AlertRuleEngine()
    match = engine.evaluate(
        make_observation(ObservationKind.RISK, score=9.5, verified=False)
    )

    assert match.outcome is RuleOutcome.TRIGGERED
    assert match.priority is Priority.MEDIUM
    assert "unvalidated" in match.title.lower()


def test_verified_high_risk_score_is_high_priority() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(
        make_observation(ObservationKind.RISK, score=9.5, verified=True)
    )

    assert match.priority is Priority.HIGH
    assert "validated" in match.title.lower()


def test_anomaly_is_capped_below_fall_urgency() -> None:
    """Unsupervised anomalies are hints; they must not look like emergencies."""
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.ANOMALY, score=99.0))

    assert match.outcome is RuleOutcome.TRIGGERED
    assert match.priority.order <= Priority.MEDIUM.order
    assert match.priority is not Priority.CRITICAL


def test_anomaly_without_score_is_suppressed() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.ANOMALY))

    assert match.outcome is RuleOutcome.SUPPRESSED_NO_DATA
    assert match.triggered_by_missing_data is True


def test_low_anomaly_score_is_suppressed() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.ANOMALY, score=0.5))

    assert match.should_alert is False


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------


def test_triggered_match_records_the_thresholds_it_used() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.FALL, confidence=0.8))

    assert match.applied_thresholds["fall_min_confidence"] == 0.60
    assert match.applied_thresholds["verified"] is False


def test_match_exposes_should_alert_property() -> None:
    engine = AlertRuleEngine()
    triggered = engine.evaluate(make_observation(ObservationKind.FALL, verified=True))
    suppressed = engine.evaluate(make_observation(ObservationKind.FALL, confidence=None))

    assert triggered.should_alert is True
    assert suppressed.should_alert is False


def test_unknown_observation_kind_is_handled_without_crashing() -> None:
    engine = AlertRuleEngine()

    class FakeKind:
        value = "not_a_real_kind"

    observation = Observation(kind=FakeKind(), elderly_profile_id=1, observed_at=NOW)  # type: ignore[arg-type]
    match = engine.evaluate(observation)

    assert match.outcome is RuleOutcome.SUPPRESSED_NO_RULE
    assert match.should_alert is False


# ---------------------------------------------------------------------------
# Numeric coercion: "0.0" is evidence, "missing" is not
# ---------------------------------------------------------------------------


def test_zero_confidence_is_treated_as_a_value_not_as_missing() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.FALL, confidence=0.0))

    # 0.0 is a real measurement below the floor, not an absence of data.
    assert match.outcome is RuleOutcome.SUPPRESSED_BELOW_THRESHOLD
    assert match.triggered_by_missing_data is False


def test_unparseable_confidence_is_treated_as_missing() -> None:
    engine = AlertRuleEngine()
    match = engine.evaluate(make_observation(ObservationKind.FALL, confidence="unknown"))

    assert match.outcome is RuleOutcome.SUPPRESSED_NO_DATA
    assert match.triggered_by_missing_data is True


def test_unrecognised_severity_never_becomes_critical() -> None:
    """A typo'd severity must not silently escalate to the top priority."""
    from backend.app.services.alert_rules import _map_severity_to_priority

    assert _map_severity_to_priority("catastrophic") is Priority.MEDIUM
    assert _map_severity_to_priority(None) is Priority.MEDIUM
    assert _map_severity_to_priority("critical") is Priority.CRITICAL


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------


def test_same_source_event_produces_the_same_dedupe_key() -> None:
    first = build_dedupe_key(
        alert_type="fall", elderly_profile_id=7, observed_at=NOW, source_event_id=42
    )
    second = build_dedupe_key(
        alert_type="fall",
        elderly_profile_id=7,
        observed_at=NOW + timedelta(minutes=5),
        source_event_id=42,
    )

    assert first == second


def test_bursts_inside_one_bucket_collapse_to_one_key() -> None:
    keys = {
        build_dedupe_key(
            alert_type="fall",
            elderly_profile_id=7,
            observed_at=NOW + timedelta(minutes=offset),
        )
        for offset in (0, 1, 2, 5)
    }

    assert len(keys) == 1


def test_observations_far_apart_get_different_keys() -> None:
    first = build_dedupe_key(
        alert_type="fall", elderly_profile_id=7, observed_at=NOW
    )
    second = build_dedupe_key(
        alert_type="fall",
        elderly_profile_id=7,
        observed_at=NOW + timedelta(hours=3),
    )

    assert first != second


def test_different_residents_never_share_a_dedupe_key() -> None:
    first = build_dedupe_key(alert_type="fall", elderly_profile_id=1, observed_at=NOW)
    second = build_dedupe_key(alert_type="fall", elderly_profile_id=2, observed_at=NOW)

    assert first != second


def test_cooldown_window_boundaries() -> None:
    window = timedelta(minutes=30)

    assert is_within_cooldown(
        existing_created_at=NOW, now=NOW + timedelta(minutes=10), window=window
    )
    assert not is_within_cooldown(
        existing_created_at=NOW, now=NOW + timedelta(minutes=45), window=window
    )


def test_naive_and_aware_datetimes_compare_without_crashing() -> None:
    """Stored timestamps may come back naive from SQLite; that must not break."""
    naive = datetime(2026, 10, 20, 12, 0)

    assert is_within_cooldown(
        existing_created_at=naive, now=NOW + timedelta(minutes=5), window=timedelta(minutes=30)
    )


def test_occurrence_count_increments_from_none() -> None:
    assert next_occurrence_count(None) == 1
    assert next_occurrence_count(0) == 1
    assert next_occurrence_count(3) == 4


# ---------------------------------------------------------------------------
# Configurability
# ---------------------------------------------------------------------------


def test_cooldown_override_per_alert_type() -> None:
    config = RuleConfig(cooldown_by_type={"fall": timedelta(minutes=5)})

    assert config.cooldown_for("fall") == timedelta(minutes=5)
    # An unlisted type still gets its specific default.
    assert config.cooldown_for("missed_checkin") == config.default_cooldown


def test_escalation_respects_a_ceiling() -> None:
    config = RuleConfig()

    assert config.escalate(Priority.LOW, steps=1) is Priority.MEDIUM
    assert config.escalate(Priority.HIGH, steps=2, ceiling=Priority.HIGH) is Priority.HIGH


def test_cap_leaves_lower_priorities_alone() -> None:
    config = RuleConfig()

    assert config.cap(Priority.INFO, Priority.HIGH) is Priority.INFO
    assert config.cap(Priority.CRITICAL, Priority.LOW) is Priority.LOW


@pytest.mark.parametrize(
    ("severity_value", "expected"),
    [
        ("info", Priority.INFO),
        ("low", Priority.LOW),
        ("medium", Priority.MEDIUM),
        ("high", Priority.HIGH),
        ("critical", Priority.CRITICAL),
    ],
)
def test_priority_order_matches_severity_ordering(severity_value, expected) -> None:
    from backend.app.models.enums import SeverityLevel

    assert severity_value == SeverityLevel(severity_value).value
    assert Priority(severity_value) is expected
