-- ============================================================================
-- v_medication_adherence_daily
--
-- One row per (elderly_profile_id, medication_schedule_id, day): what happened
-- to the doses that were due that day.
--
-- The counters that matter
-- ------------------------
--   resolved_doses = taken + missed + skipped   (an outcome was recorded)
--   taken_doses    = the outcomes that were positive
--
-- `resolved_doses` is the denominator of the "medication adherence rate" KPI,
-- exactly as `backend/app/services/kpi_definitions.py` defines it.
--
-- The honest limitation, repeated here because it is the one that matters
-- ---------------------------------------------------------------------------
-- This view can only count doses that were *logged*. A dose that was never
-- logged at all cannot be counted — not here, not in the KPI. So this measures
-- adherence among logged doses, and it cannot prove that an unlogged dose was
-- not taken. Always read `resolved_doses` next to `taken_doses`.
--
-- Why the medication is identified by schedule, not by name
-- --------------------------------------------------------
-- `medication_name` is free text. Two schedules may carry the same name, and
-- one schedule may be renamed. The schedule id is the stable key; the name is
-- carried along so a report can be read without a second lookup.
-- ============================================================================

DROP VIEW IF EXISTS v_medication_adherence_daily;

CREATE OR REPLACE VIEW v_medication_adherence_daily AS
SELECT
    ms.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    d.medication_schedule_id,
    ms.medication_name,
    d.scheduled_for::date AS dose_day,

    -- Volume
    COUNT(*) AS total_dose_logs,

    -- Breakdown by status
    COUNT(*) FILTER (WHERE d.status = 'taken') AS taken_count,
    COUNT(*) FILTER (WHERE d.status = 'missed') AS missed_count,
    COUNT(*) FILTER (WHERE d.status = 'skipped') AS skipped_count,
    COUNT(*) FILTER (WHERE d.status = 'scheduled') AS scheduled_count,
    COUNT(*) FILTER (WHERE d.status = 'cancelled') AS cancelled_count,

    -- Outcomes that were actually recorded (the KPI denominator).
    COUNT(*) FILTER (WHERE d.status IN ('taken', 'missed', 'skipped')) AS resolved_doses,

    -- Outcomes that were positive.
    COUNT(*) FILTER (WHERE d.status = 'taken') AS taken_doses
FROM medication_dose_logs d
JOIN medication_schedules ms
    ON ms.id = d.medication_schedule_id
JOIN elderly_profiles p
    ON p.id = ms.elderly_profile_id
GROUP BY
    ms.elderly_profile_id,
    p.display_name,
    d.medication_schedule_id,
    ms.medication_name,
    d.scheduled_for::date;
