-- ============================================================================
-- v_checkin_completion_daily
--
-- One row per (elderly_profile_id, day): what happened to the check-ins that
-- were due that day.
--
-- The counters that matter
-- ------------------------
--   resolved_checkins  = taken + missed + skipped   (an outcome was recorded)
--   taken_checkins     = the outcomes that were positive
--   excluded_pending   = scheduled + cancelled       (no outcome yet)
--
-- `resolved_checkins` is the denominator of the "check-in completion rate"
-- KPI, exactly as `backend/app/services/kpi_definitions.py` defines it.
-- `excluded_pending` is reported next to it on purpose: a day where most
-- check-ins are still `scheduled` is not a day where residents failed to
-- check in, it is a day where the day has not finished yet.
--
-- Which day does a check-in belong to?
-- ------------------------------------
-- `performed_at` when the check-in happened, otherwise the time it was
-- scheduled for, otherwise the time the row was created. A check-in with no
-- outcome still has to land on a row somewhere, and this rule keeps it on the
-- day it was actually due.
--
-- Honest limits
-- --------------
-- * A missing check-in is not an emergency. Nothing here escalates silence.
-- * `excluded_pending` counts are *not* failures.
-- ============================================================================

DROP VIEW IF EXISTS v_checkin_completion_daily;

CREATE OR REPLACE VIEW v_checkin_completion_daily AS
SELECT
    c.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    COALESCE(c.performed_at, c.scheduled_for, c.created_at)::date AS checkin_day,

    -- Volume
    COUNT(*) AS total_checkins,

    -- Breakdown by status
    COUNT(*) FILTER (WHERE c.status = 'taken') AS taken_count,
    COUNT(*) FILTER (WHERE c.status = 'missed') AS missed_count,
    COUNT(*) FILTER (WHERE c.status = 'skipped') AS skipped_count,
    COUNT(*) FILTER (WHERE c.status = 'scheduled') AS scheduled_count,
    COUNT(*) FILTER (WHERE c.status = 'cancelled') AS cancelled_count,

    -- Outcomes that were actually recorded (the KPI denominator).
    COUNT(*) FILTER (WHERE c.status IN ('taken', 'missed', 'skipped')) AS resolved_checkins,

    -- Outcomes that were positive.
    COUNT(*) FILTER (WHERE c.status = 'taken') AS taken_checkins,

    -- Not yet an outcome — reported, never treated as a failure.
    COUNT(*) FILTER (WHERE c.status IN ('scheduled', 'cancelled')) AS excluded_pending
FROM checkins c
JOIN elderly_profiles p
    ON p.id = c.elderly_profile_id
GROUP BY
    c.elderly_profile_id,
    p.display_name,
    COALESCE(c.performed_at, c.scheduled_for, c.created_at)::date;
