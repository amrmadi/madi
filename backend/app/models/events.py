"""AI / monitoring domain: model runs, activity events, and detected events.

Separation of concerns that this module encodes
-----------------------------------------------
    ModelRun         "a model was executed" — provenance: which model, which
                     version, on what input, with what metrics or error.
    ActivityEvent    what the resident was observed doing (from inference or
                     manual entry).
    FallEvent        a fall detection result.
    AnomalyEvent     a behavioural deviation from the resident's baseline.
    RiskEvent        a computed risk observation (e.g. fall_risk score).

All four event tables share the same shape (`elderly_profile_id`,
`occurred_at`, `severity`, `confidence`, `source`, optional `model_run_id`) so
the alert engine and the analytics layer can treat them uniformly.

`source` exists specifically so that simulated/demo data is always
distinguishable from real sensor data — a hard requirement of this project.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, utcnow
from backend.app.models.enums import (
    ActivityType,
    EventSource,
    ModelRunStatus,
    ModelTask,
    RiskCategory,
    SeverityLevel,
)


class ModelRun(Base):
    """Execution record for one AI model invocation.

    This is the bridge between the database and the `ai/` package: the backend
    writes a `ModelRun` row every time a model is called, so every prediction in
    the event tables points back to exactly which model produced it.

    `input_ref` is a lightweight pointer (a file path, window id, or dataset
    row id) rather than the raw payload, to avoid duplicating large blobs.
    """

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    task: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False, default="unversioned")

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ModelRunStatus.PENDING.value
    )

    # Optional: runs can also be batch jobs that are not tied to a person.
    elderly_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Who/what triggered the run (nullable = system/scheduled).
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    input_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Model metrics as JSON text (e.g. {"confidence": 0.91, "latency_ms": 42}).
    # A JSON column is used so different model types can log different metrics
    # without a schema change.
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Relationships ----
    activity_events: Mapped[list["ActivityEvent"]] = relationship(back_populates="model_run")
    fall_events: Mapped[list["FallEvent"]] = relationship(back_populates="model_run")
    anomaly_events: Mapped[list["AnomalyEvent"]] = relationship(back_populates="model_run")
    risk_events: Mapped[list["RiskEvent"]] = relationship(back_populates="model_run")

    __table_args__ = (
        CheckConstraint(
            "task IN ('fall_detection', 'activity_recognition', 'behavioral_analysis')",
            name="model_run_task_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="model_run_status_valid",
        ),
        # A finished run must have finished_at set; an unfinished one must not.
        CheckConstraint(
            "(status IN ('pending', 'running') AND finished_at IS NULL)"
            " OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL)",
            name="model_run_lifecycle_consistent",
        ),
        Index("ix_model_runs_task_started", "task", "started_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ModelRun id={self.id} task={self.task} "
            f"model={self.model_name} status={self.status}>"
        )


class ActivityEvent(Base):
    """A recognized (or manually recorded) activity over a time window."""

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EventSource.SIMULATED.value
    )
    room_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="activity_events")
    model_run: Mapped["ModelRun | None"] = relationship(back_populates="activity_events")

    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('walking', 'standing', 'sitting', 'lying', 'eating',"
            " 'sleeping', 'toileting', 'unknown')",
            name="activity_type_valid",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="activity_confidence_range",
        ),
        CheckConstraint(
            "source IN ('simulated', 'sensor', 'manual_entry', 'imported_dataset', 'model')",
            name="activity_source_valid",
        ),
        Index("ix_activity_events_profile_started", "elderly_profile_id", "started_at"),
        Index("ix_activity_events_type_started", "activity_type", "started_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ActivityEvent id={self.id} type={self.activity_type}>"


class FallEvent(Base):
    """A fall-detection observation (from the model, or reported by a person)."""

    __tablename__ = "fall_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    is_fall: Mapped[bool] = mapped_column(nullable=False, default=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SeverityLevel.CRITICAL.value
    )

    location_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EventSource.SIMULATED.value
    )

    # Whether a human confirmed the event (essential: fall detectors produce
    # false positives, so we record verification separately from the prediction).
    was_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="fall_events")
    model_run: Mapped["ModelRun | None"] = relationship(back_populates="fall_events")

    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="fall_confidence_range",
        ),
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="fall_severity_valid",
        ),
        CheckConstraint(
            "source IN ('simulated', 'sensor', 'manual_entry', 'imported_dataset', 'model')",
            name="fall_source_valid",
        ),
        Index("ix_fall_events_profile_occurred", "elderly_profile_id", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FallEvent id={self.id} is_fall={self.is_fall} conf={self.confidence}>"


class AnomalyEvent(Base):
    """A behavioural deviation detected by `ai/behavioral_analysis`."""

    __tablename__ = "anomaly_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    anomaly_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Higher = more unusual. Scale depends on the detector; `anomaly_type` and
    # `model_run_id` record which method produced the score.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SeverityLevel.MEDIUM.value
    )

    baseline_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EventSource.SIMULATED.value
    )

    was_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="anomaly_events")
    model_run: Mapped["ModelRun | None"] = relationship(back_populates="anomaly_events")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="anomaly_severity_valid",
        ),
        CheckConstraint(
            "score IS NULL OR score >= 0.0",
            name="anomaly_score_non_negative",
        ),
        CheckConstraint(
            "source IN ('simulated', 'sensor', 'manual_entry', 'imported_dataset', 'model')",
            name="anomaly_source_valid",
        ),
        Index("ix_anomaly_events_profile_occurred", "elderly_profile_id", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AnomalyEvent id={self.id} type={self.anomaly_type} score={self.score}>"


class RiskEvent(Base):
    """A computed risk observation about a resident.

    Unlike the other event tables this one is about a *level*, not a moment:
    a risk score is meaningful over an assessment period, hence `assessed_at`
    and `valid_until` instead of a single `occurred_at`.
    """

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elderly_profile_id: Mapped[int] = mapped_column(
        ForeignKey("elderly_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    category: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SeverityLevel.MEDIUM.value
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EventSource.SIMULATED.value
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    elderly_profile: Mapped["ElderlyProfile"] = relationship(back_populates="risk_events")
    model_run: Mapped["ModelRun | None"] = relationship(back_populates="risk_events")

    __table_args__ = (
        CheckConstraint(
            "category IN ('fall_risk', 'malnutrition', 'dehydration', 'cognitive_decline',"
            " 'social_isolation', 'medication_adherence', 'general')",
            name="risk_category_valid",
        ),
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="risk_severity_valid",
        ),
        CheckConstraint(
            "score IS NULL OR score >= 0.0",
            name="risk_score_non_negative",
        ),
        CheckConstraint(
            "source IN ('simulated', 'sensor', 'manual_entry', 'imported_dataset', 'model')",
            name="risk_source_valid",
        ),
        Index("ix_risk_events_profile_assessed", "elderly_profile_id", "assessed_at"),
        Index("ix_risk_events_category", "category", "assessed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RiskEvent id={self.id} category={self.category} severity={self.severity}>"
