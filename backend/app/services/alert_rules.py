"""Configurable, explainable alert rule engine.

What this module is
-------------------
A small, declarative rules engine that turns *observations* (a fall event, a
missed check-in, a low-confidence anomaly) into *alerts* with a priority,
deduplication, and a lifecycle. It is deliberately **pure**: no database, no
HTTP. The router/service layer feeds it observations and persists the decision.

Three ideas that this design encodes
------------------------------------
1. **Operational priority != medical risk.**
   `priority` answers "how quickly should a caregiver *look* at this?" It is an
   operational triage signal produced by rules. It is NOT a diagnosis, and it
   is NOT the same as a medically validated risk score. A fall detector's
   unverified guess is urgent to *check*, but that says nothing about the
   resident's actual clinical condition. The two are recorded separately
   (`severity`/priority vs. a verified `risk_events` row that a human or a
   validated assessment produced) and never conflated.

2. **Missing data is not an emergency.**
   A gap in check-ins, a null confidence, or a sensor that stopped reporting is
   a *data-quality* problem. It proves nothing about the resident's safety until
   a human confirms it. Such observations map to `DATA_GAP` and are capped at
   low/info priority. Escalating them to emergency level would train caregivers
   to ignore alarms — the opposite of helpful.

3. **Rules are data, not code.**
   A `RuleConfig` object holds every threshold. Different homes can use
   different thresholds without editing this file, and the thresholds a decision
   used are returned alongside the decision (see `RuleMatch`), so an alert can
   always explain *why* it fired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from backend.app.models.enums import AlertType, SeverityLevel
from backend.app.schemas.alerts_engine import ObservationKind


class RuleOutcome(str, Enum):
    """Why the engine did (or did not) produce an alert.

    Recorded explicitly so tests and the audit log can distinguish "no rule
    applied" from "a rule applied but the input was missing".
    """

    TRIGGERED = "triggered"
    SUPPRESSED_NO_DATA = "suppressed_no_data"
    SUPPRESSED_BELOW_THRESHOLD = "suppressed_below_threshold"
    SUPPRESSED_NO_RULE = "suppressed_no_rule"


class Priority(str, Enum):
    """Operational triage priority — the *only* thing rules assign.

    Independent from clinical risk. `CRITICAL` means "a person should look now",
    not "the resident is medically critical".
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def order(self) -> int:
        """Numeric rank for comparisons (higher = more urgent)."""
        return _PRIORITY_ORDER[self]


_PRIORITY_ORDER = {
    Priority.INFO: 0,
    Priority.LOW: 1,
    Priority.MEDIUM: 2,
    Priority.HIGH: 3,
    Priority.CRITICAL: 4,
}


def _map_severity_to_priority(severity: str | None) -> Priority:
    """Translate a stored `severity` string into an operational priority."""
    try:
        return Priority(severity) if severity else Priority.MEDIUM
    except ValueError:
        # An unrecognised severity must never silently become CRITICAL. Falling
        # back to MEDIUM keeps a bad value visible without crying wolf.
        return Priority.MEDIUM


# ---------------------------------------------------------------------------
# Configuration — all thresholds live here, so behaviour is reproducible and
# every alert can explain which numbers produced it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleConfig:
    """Every tunable threshold the engine understands.

    Defaults are deliberately conservative: the engine prefers to *not* raise an
    emergency when the evidence is weak.
    """

    # --- Fall detection ---
    # A fall alert needs at least this model confidence. Below it, we record a
    # lower-priority observation instead of an emergency.
    fall_min_confidence: float = 0.60
    # Below this, we don't trust the detection at all (recorded as suppressed).
    fall_report_floor: float = 0.30
    # Verified falls are always critical, regardless of model confidence.
    fall_verified_priority: Priority = Priority.CRITICAL

    # --- Data gaps (missing sensor / check-in data) ---
    # How long a data gap must last before it is even worth mentioning.
    data_gap_mention_after: timedelta = timedelta(hours=6)
    # A data gap is NEVER allowed above this priority. This is the direct
    # encoding of "missing data alone must not imply an emergency".
    data_gap_max_priority: Priority = Priority.LOW

    # --- Missed check-ins ---
    # A check-in is only "missed" this long after it was due. Being a little
    # late is normal; that is not an emergency either.
    checkin_grace_period: timedelta = timedelta(hours=2)
    missed_checkin_priority: Priority = Priority.MEDIUM
    # Two consecutive missed check-ins raise the priority one step, but never
    # to CRITICAL — repeated lateness is a pattern worth a look, not a fall.
    missed_checkin_repeat_priority: Priority = Priority.HIGH

    # --- Missed medication ---
    # Missed medication matters clinically, but a single late dose is not a
    # 3am emergency. Default to medium, escalating with repeats.
    missed_medication_priority: Priority = Priority.MEDIUM
    missed_medication_repeat_priority: Priority = Priority.HIGH

    # --- Anomaly (behavioural deviation) ---
    # Anomaly detection is unsupervised and cannot be "correct" in a validated
    # sense, so anomalies are capped below fall-level urgency.
    anomaly_min_score: float = 2.0
    anomaly_priority: Priority = Priority.LOW
    anomaly_high_score: float = 3.5
    anomaly_high_priority: Priority = Priority.MEDIUM
    anomaly_max_priority: Priority = Priority.MEDIUM

    # --- Risk (validated assessment, not a model guess) ---
    # Only a *verified* risk assessment may reach high priority. This is the
    # validated-medical-risk side of the priority/risk distinction.
    risk_priority: Priority = Priority.MEDIUM
    risk_high_priority: Priority = Priority.HIGH
    risk_high_score: float = 7.0

    # --- Deduplication / cooldown ---
    # How long an alert with the same dedupe_key suppresses new alerts. A new
    # occurrence inside the window increments the existing alert instead of
    # creating a duplicate notification.
    default_cooldown: timedelta = timedelta(minutes=30)
    fall_cooldown: timedelta = timedelta(minutes=15)
    cooldown_by_type: dict[str, timedelta] = field(default_factory=dict)

    def cooldown_for(self, alert_type: str) -> timedelta:
        """Cooldown for a given alert type, with the per-type override applied."""
        if alert_type in self.cooldown_by_type:
            return self.cooldown_by_type[alert_type]
        if alert_type == AlertType.FALL.value:
            return self.fall_cooldown
        return self.default_cooldown

    def cap(self, priority: Priority, ceiling: Priority) -> Priority:
        """Return `priority`, but never above `ceiling`."""
        return priority if priority.order <= ceiling.order else ceiling

    def escalate(self, priority: Priority, steps: int = 1, ceiling: Priority | None = None) -> Priority:
        """Raise a priority by `steps` ranks, optionally bounded by a ceiling."""
        ranks = [p for p in Priority]
        ordered = sorted(ranks, key=lambda p: p.order)
        index = min(ordered.index(priority) + steps, len(ordered) - 1)
        raised = ordered[index]
        return self.cap(raised, ceiling) if ceiling is not None else raised


# ---------------------------------------------------------------------------
# Inputs and outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """One thing the engine is asked to judge.

    `observed_at` is the time the *underlying thing* happened (for example a
    fall at 03:12), which may differ from when we are told about it. Keeping
    both is what lets us report detection latency honestly.
    """

    kind: ObservationKind
    elderly_profile_id: int
    observed_at: datetime
    # Free-form values the rules read: confidence, score, minutes_late, etc.
    values: dict[str, Any] = field(default_factory=dict)
    # Stable key identifying the *same* underlying problem, for deduplication.
    # e.g. "fall:profile-3:2026-10-20T03:12" collapses repeated tells about one fall.
    dedupe_key: str | None = None
    # Set when a human has already confirmed the underlying event.
    verified: bool = False
    source_event_type: str | None = None
    source_event_id: int | None = None


@dataclass(frozen=True)
class RuleMatch:
    """The engine's decision, with the reasoning attached.

    Returning the thresholds that were applied (rather than just a boolean)
    makes alerts *explainable*: the UI and the audit log can show exactly which
    rule and which numbers produced the priority.
    """

    outcome: RuleOutcome
    alert_type: str | None
    priority: Priority
    title: str
    message: str
    dedupe_key: str | None
    rule_name: str
    # Which config values the decision used, for auditability.
    applied_thresholds: dict[str, Any] = field(default_factory=dict)
    # True when the trigger was absence of data rather than a positive signal.
    triggered_by_missing_data: bool = False

    @property
    def should_alert(self) -> bool:
        """Whether this match should become (or bump) an alert row."""
        return self.outcome is RuleOutcome.TRIGGERED


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class AlertRuleEngine:
    """Applies `RuleConfig` to `Observation`s and explains each decision."""

    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _as_float(value: Any) -> float | None:
        """Coerce to float, returning None for missing/unusable values.

        Returning None (rather than raising or defaulting to 0) is important:
        the engine must be able to tell "confidence was 0.0" from "confidence
        was never reported", because only the first is real evidence.
        """
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _no_alert(
        self,
        outcome: RuleOutcome,
        *,
        alert_type: str | None,
        rule_name: str,
        reason: str,
        priority: Priority = Priority.INFO,
        missing_data: bool = False,
        thresholds: dict[str, Any] | None = None,
    ) -> RuleMatch:
        """Build a 'do not alert' decision that still explains itself."""
        return RuleMatch(
            outcome=outcome,
            alert_type=alert_type,
            priority=priority,
            title="",
            message=reason,
            dedupe_key=None,
            rule_name=rule_name,
            applied_thresholds=thresholds or {},
            triggered_by_missing_data=missing_data,
        )

    # -- public API ------------------------------------------------------

    def evaluate(self, observation: Observation) -> RuleMatch:
        """Judge one observation and return the decision with its reasoning."""
        handler = {
            ObservationKind.FALL: self._evaluate_fall,
            ObservationKind.DATA_GAP: self._evaluate_data_gap,
            ObservationKind.MISSED_CHECKIN: self._evaluate_missed_checkin,
            ObservationKind.MISSED_MEDICATION: self._evaluate_missed_medication,
            ObservationKind.ANOMALY: self._evaluate_anomaly,
            ObservationKind.RISK: self._evaluate_risk,
        }.get(observation.kind)

        if handler is None:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_NO_RULE,
                alert_type=None,
                rule_name="unknown",
                reason=f"No rule is configured for observation kind {observation.kind!r}.",
            )
        return handler(observation)

    # -- individual rules ------------------------------------------------

    def _evaluate_fall(self, obs: Observation) -> RuleMatch:
        """Falls are the one thing allowed to reach CRITICAL — and only falls.

        A *verified* fall is critical regardless of confidence: a human already
        confirmed it, so model uncertainty no longer matters operationally.
        """
        confidence = self._as_float(obs.values.get("confidence"))
        thresholds = {
            "fall_min_confidence": self.config.fall_min_confidence,
            "fall_report_floor": self.config.fall_report_floor,
            "verified": obs.verified,
        }

        if obs.verified:
            return RuleMatch(
                outcome=RuleOutcome.TRIGGERED,
                alert_type=AlertType.FALL.value,
                priority=self.config.fall_verified_priority,
                title="Verified fall reported",
                message=(
                    "A fall at this resident has been confirmed by a person. "
                    "This is an operational priority for response, not a medical "
                    "diagnosis."
                ),
                dedupe_key=obs.dedupe_key,
                rule_name="fall.verified",
                applied_thresholds=thresholds,
            )

        if confidence is None:
            # Unknown confidence: we refuse to invent one, and we refuse to
            # escalate on absent evidence.
            return self._no_alert(
                RuleOutcome.SUPPRESSED_NO_DATA,
                alert_type=AlertType.FALL.value,
                rule_name="fall.unverified",
                reason=(
                    "A possible fall was reported without a model confidence "
                    "value. Missing confidence is not evidence of a fall, so no "
                    "emergency is raised; record the detection for review."
                ),
                priority=Priority.LOW,
                missing_data=True,
                thresholds=thresholds,
            )

        if confidence < self.config.fall_report_floor:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_BELOW_THRESHOLD,
                alert_type=AlertType.FALL.value,
                rule_name="fall.unverified",
                reason=(
                    f"Fall confidence {confidence:.2f} is below the reporting "
                    f"floor {self.config.fall_report_floor:.2f}; treated as noise."
                ),
                priority=Priority.INFO,
                thresholds=thresholds,
            )

        if confidence < self.config.fall_min_confidence:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_BELOW_THRESHOLD,
                alert_type=AlertType.FALL.value,
                rule_name="fall.unverified",
                reason=(
                    f"Fall confidence {confidence:.2f} is below the alert "
                    f"threshold {self.config.fall_min_confidence:.2f}. Recorded "
                    "for review at low priority; not treated as an emergency."
                ),
                priority=Priority.LOW,
                thresholds=thresholds,
            )

        # Unverified but confident: worth an urgent look, and explicitly labelled
        # as unverified so nobody mistakes it for a confirmed clinical event.
        return RuleMatch(
            outcome=RuleOutcome.TRIGGERED,
            alert_type=AlertType.FALL.value,
            priority=Priority.HIGH,
            title="Possible fall detected (unverified)",
            message=(
                f"A fall was detected with confidence {confidence:.2f}. This is "
                "an unverified model detection: it is an operational priority to "
                "check on the resident, not a confirmed medical event."
            ),
            dedupe_key=obs.dedupe_key,
            rule_name="fall.unverified",
            applied_thresholds=thresholds,
        )

    def _evaluate_data_gap(self, obs: Observation) -> RuleMatch:
        """Missing data is a data-quality signal — never an emergency.

        This rule is the direct implementation of the requirement that *absence
        of data alone must not imply an emergency*. It is capped at
        `data_gap_max_priority` even if the gap is enormous.
        """
        minutes = self._as_float(obs.values.get("gap_minutes"))
        thresholds = {
            "data_gap_mention_after_minutes": (
                self.config.data_gap_mention_after.total_seconds() / 60
            ),
            "data_gap_max_priority": self.config.data_gap_max_priority.value,
        }

        if minutes is None:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_NO_DATA,
                alert_type=AlertType.SYSTEM.value,
                rule_name="data_gap",
                reason="A data gap was reported without a duration; nothing to judge.",
                missing_data=True,
                thresholds=thresholds,
            )

        if minutes < self.config.data_gap_mention_after.total_seconds() / 60:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_BELOW_THRESHOLD,
                alert_type=AlertType.SYSTEM.value,
                rule_name="data_gap",
                reason=(
                    f"Data gap of {minutes:.0f} min is shorter than the "
                    f"{self.config.data_gap_mention_after.total_seconds() / 3600:.1f} h "
                    "mention threshold; ordinary sensor jitter."
                ),
                thresholds=thresholds,
            )

        # Priority rises with the length of the gap up to the hard ceiling. It
        # can never reach CRITICAL: no amount of silence proves a person is hurt.
        priority = self.config.data_gap_max_priority
        ceiling = self.config.data_gap_max_priority
        priority = self.config.cap(priority, ceiling)

        dedupe_noun = obs.values.get("gap_kind", "sensor")
        return RuleMatch(
            outcome=RuleOutcome.TRIGGERED,
            alert_type=AlertType.SYSTEM.value,
            priority=priority,
            title=f"No {dedupe_noun} data for {minutes / 60:.1f} h",
            message=(
                f"No {dedupe_noun} data has been received for {minutes / 60:.1f} "
                "hours. This is a data-quality issue, not evidence that the "
                "resident is unsafe. Check the device or connectivity; do not "
                "treat silence as an emergency."
            ),
            dedupe_key=obs.dedupe_key,
            rule_name="data_gap",
            applied_thresholds=thresholds,
            triggered_by_missing_data=True,
        )

    def _evaluate_missed_checkin(self, obs: Observation) -> RuleMatch:
        """A late check-in escalates with repetition, but never to CRITICAL."""
        minutes_late = self._as_float(obs.values.get("minutes_late"))
        threshold_minutes = self.config.checkin_grace_period.total_seconds() / 60
        consecutive = obs.values.get("consecutive_misses")
        thresholds = {
            "checkin_grace_period_minutes": threshold_minutes,
            "consecutive_misses": consecutive,
        }

        if minutes_late is None:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_NO_DATA,
                alert_type=AlertType.MISSED_CHECKIN.value,
                rule_name="missed_checkin",
                reason="A check-in was reported as missed without a due time.",
                missing_data=True,
                thresholds=thresholds,
            )

        if minutes_late <= threshold_minutes:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_BELOW_THRESHOLD,
                alert_type=AlertType.MISSED_CHECKIN.value,
                rule_name="missed_checkin",
                reason=(
                    f"Check-in is {minutes_late:.0f} min late, within the "
                    f"{threshold_minutes:.0f} min grace period."
                ),
                thresholds=thresholds,
            )

        try:
            repeats = int(consecutive or 1)
        except (TypeError, ValueError):
            repeats = 1

        priority = self.config.missed_checkin_priority
        if repeats >= 2:
            priority = self.config.missed_checkin_repeat_priority
        # Explicitly bounded below CRITICAL: a pattern of missing check-ins is a
        # concern to follow up, not a proven emergency.
        priority = self.config.cap(priority, Priority.HIGH)

        return RuleMatch(
            outcome=RuleOutcome.TRIGGERED,
            alert_type=AlertType.MISSED_CHECKIN.value,
            priority=priority,
            title="Check-in overdue",
            message=(
                f"A scheduled check-in is {minutes_late / 60:.1f} h overdue "
                f"({repeats} consecutive miss(es)). Follow up; this does not by "
                "itself indicate an emergency."
            ),
            dedupe_key=obs.dedupe_key,
            rule_name="missed_checkin",
            applied_thresholds=thresholds,
        )

    def _evaluate_missed_medication(self, obs: Observation) -> RuleMatch:
        """Repeated missed doses escalate to HIGH, never CRITICAL."""
        due_minutes = self._as_float(obs.values.get("minutes_late"))
        consecutive = obs.values.get("consecutive_misses")
        thresholds = {"consecutive_misses": consecutive}

        if due_minutes is None or due_minutes <= 0:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_NO_DATA,
                alert_type=AlertType.MISSED_MEDICATION.value,
                rule_name="missed_medication",
                reason="A dose was reported as missed without a positive lateness value.",
                missing_data=due_minutes is None,
                thresholds=thresholds,
            )

        try:
            repeats = int(consecutive or 1)
        except (TypeError, ValueError):
            repeats = 1

        priority = self.config.missed_medication_priority
        if repeats >= 3:
            priority = self.config.missed_medication_repeat_priority
        priority = self.config.cap(priority, Priority.HIGH)

        return RuleMatch(
            outcome=RuleOutcome.TRIGGERED,
            alert_type=AlertType.MISSED_MEDICATION.value,
            priority=priority,
            title="Medication doses missed",
            message=(
                f"{repeats} consecutive scheduled dose(s) were not recorded as "
                "taken. Adherence matters clinically; this system does not give "
                "medical advice. Escalate to the prescriber if the pattern continues."
            ),
            dedupe_key=obs.dedupe_key,
            rule_name="missed_medication",
            applied_thresholds=thresholds,
        )

    def _evaluate_anomaly(self, obs: Observation) -> RuleMatch:
        """Unsupervised anomalies are capped: they are hints, not conclusions."""
        score = self._as_float(obs.values.get("score"))
        thresholds = {
            "anomaly_min_score": self.config.anomaly_min_score,
            "anomaly_high_score": self.config.anomaly_high_score,
            "anomaly_max_priority": self.config.anomaly_max_priority.value,
        }

        if score is None:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_NO_DATA,
                alert_type=AlertType.ANOMALY.value,
                rule_name="anomaly",
                reason=(
                    "An anomaly was reported without a score. An unscoreable "
                    "anomaly is not actionable, so nothing is raised."
                ),
                missing_data=True,
                thresholds=thresholds,
            )

        if score < self.config.anomaly_min_score:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_BELOW_THRESHOLD,
                alert_type=AlertType.ANOMALY.value,
                rule_name="anomaly",
                reason=(
                    f"Anomaly score {score:.2f} is below the review threshold "
                    f"{self.config.anomaly_min_score:.2f}."
                ),
                thresholds=thresholds,
            )

        priority = (
            self.config.anomaly_high_priority
            if score >= self.config.anomaly_high_score
            else self.config.anomaly_priority
        )
        priority = self.config.cap(priority, self.config.anomaly_max_priority)

        return RuleMatch(
            outcome=RuleOutcome.TRIGGERED,
            alert_type=AlertType.ANOMALY.value,
            priority=priority,
            title="Unusual routine detected",
            message=(
                f"Activity deviated from this resident's baseline (score "
                f"{score:.2f}). Anomaly detection is unsupervised, so this is a "
                "hint worth reviewing, not a diagnosis."
            ),
            dedupe_key=obs.dedupe_key,
            rule_name="anomaly",
            applied_thresholds=thresholds,
        )

    def _evaluate_risk(self, obs: Observation) -> RuleMatch:
        """Validated risk scores rank highest among non-fall signals.

        Crucially, an *unverified* risk score cannot reach HIGH: only a
        validated assessment does. This keeps operational triage from being
        driven by unvalidated numbers.
        """
        score = self._as_float(obs.values.get("score"))
        thresholds = {
            "risk_high_score": self.config.risk_high_score,
            "verified": obs.verified,
        }

        if score is None:
            return self._no_alert(
                RuleOutcome.SUPPRESSED_NO_DATA,
                alert_type=AlertType.RISK.value,
                rule_name="risk",
                reason="A risk assessment was reported without a score.",
                missing_data=True,
                thresholds=thresholds,
            )

        if score >= self.config.risk_high_score and obs.verified:
            priority = self.config.risk_high_priority
        else:
            priority = self.config.risk_priority

        qualifier = "validated" if obs.verified else "unvalidated"
        return RuleMatch(
            outcome=RuleOutcome.TRIGGERED,
            alert_type=AlertType.RISK.value,
            priority=priority,
            title=f"{qualifier.capitalize()} risk score recorded",
            message=(
                f"A {qualifier} risk score of {score:.2f} was recorded"
                + (
                    "; this is a validated assessment and ranks as a high "
                    "operational priority for follow-up."
                    if obs.verified and score >= self.config.risk_high_score
                    else "; recorded for tracking."
                )
            ),
            dedupe_key=obs.dedupe_key,
            rule_name="risk",
            applied_thresholds=thresholds,
        )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def build_dedupe_key(
    *,
    alert_type: str,
    elderly_profile_id: int,
    observed_at: datetime,
    source_event_id: int | None = None,
    bucket: timedelta = timedelta(minutes=30),
) -> str:
    """Build a stable key identifying 'the same underlying problem'.

    Two tells about one fall must collapse into a single alert. We bucket time
    so that a burst of repeated signals inside `bucket` produces one key. An
    explicit `source_event_id` wins when present, since it is exact.
    """
    if source_event_id is not None:
        return f"{alert_type}:{elderly_profile_id}:ev{source_event_id}"

    moment = observed_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    # Floor the timestamp to the bucket start, producing a deterministic key.
    epoch_seconds = int(moment.timestamp())
    bucket_seconds = max(int(bucket.total_seconds()), 1)
    floored = (epoch_seconds // bucket_seconds) * bucket_seconds
    return f"{alert_type}:{elderly_profile_id}:t{floored}"


def is_within_cooldown(
    *,
    existing_created_at: datetime,
    now: datetime,
    window: timedelta,
) -> bool:
    """Whether an existing alert with the same dedupe_key is still 'fresh'.

    Inside the window, a repeat observation bumps `occurrence_count` on the
    existing alert instead of creating a duplicate notification.
    """
    reference = existing_created_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - reference) < window


def next_occurrence_count(previous: int | None) -> int:
    """Increment the occurrence counter for a deduplicated alert."""
    return int(previous or 0) + 1
