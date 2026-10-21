-- ============================================================================
-- v_alert_lifecycle_daily
--
-- One row per (elderly_profile_id, day): how many alerts a resident raised on
-- that day, broken down by alert type and severity, and how far each of them
-- got through the lifecycle (new -> acknowledged -> resolved / dismissed).
--
-- Why the lifecycle columns are separate
-- --------------------------------------
-- "How many alerts did Margaret have?" is not the question a caregiver asks.
-- The useful question is "how many are still sitting unacknowledged?". That is
-- why open / acknowledged / resolved / dismissed are four separate counters
-- rather than one total.
--
-- Honest limits
-- --------------
-- * A day is the alert's `created_at` cast to a date, in the database's time
--   zone. An alert acknowledged the next morning still counts against the day
--   it was raised.
-- * `distinct_caregiver_count` counts the caregivers who actually acknowledged
--   something. An alert nobody has touched contributes 0, not a made-up
--   number.
-- * This view counts alerts that *were* raised. It says nothing about alerts
--   that should have been raised and were not.
-- * No column here is a medical risk measure. `severity` is an operational
--   triage priority.
-- ============================================================================

DROP VIEW IF EXISTS v_alert_lifecycle_daily;

CREATE OR REPLACE VIEW v_alert_lifecycle_daily AS
SELECT
    a.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    a.created_at::date AS alert_day,

    -- Volume
    COUNT(*) AS total_alerts,

    -- Breakdown by alert type (the vocabulary is constrained by the
    -- `alert_type_valid` CHECK constraint on `alerts`).
    COUNT(*) FILTER (WHERE a.alert_type = 'fall') AS fall_alert_count,
    COUNT(*) FILTER (WHERE a.alert_type = 'anomaly') AS anomaly_alert_count,
    COUNT(*) FILTER (WHERE a.alert_type = 'risk') AS risk_alert_count,
    COUNT(*) FILTER (WHERE a.alert_type = 'missed_medication') AS missed_medication_alert_count,
    COUNT(*) FILTER (WHERE a.alert_type = 'missed_checkin') AS missed_checkin_alert_count,
    COUNT(*) FILTER (WHERE a.alert_type = 'system') AS system_alert_count,

    -- Breakdown by severity (operational priority, not medical risk).
    COUNT(*) FILTER (WHERE a.severity = 'info') AS info_alert_count,
    COUNT(*) FILTER (WHERE a.severity = 'low') AS low_alert_count,
    COUNT(*) FILTER (WHERE a.severity = 'medium') AS medium_alert_count,
    COUNT(*) FILTER (WHERE a.severity = 'high') AS high_alert_count,
    COUNT(*) FILTER (WHERE a.severity = 'critical') AS critical_alert_count,

    -- Lifecycle position.
    -- `open_alert_count` means "not finished yet": raised but not yet
    -- acknowledged, or acknowledged but not yet resolved or dismissed.
    COUNT(*) FILTER (WHERE a.status IN ('new', 'acknowledged')) AS open_alert_count,
    COUNT(*) FILTER (WHERE a.status = 'new') AS new_alert_count,
    COUNT(*) FILTER (WHERE a.status = 'acknowledged') AS acknowledged_alert_count,
    COUNT(*) FILTER (WHERE a.status = 'resolved') AS resolved_alert_count,
    COUNT(*) FILTER (WHERE a.status = 'dismissed') AS dismissed_alert_count,

    -- How many different caregivers touched these alerts that day.
    COUNT(DISTINCT a.acknowledged_by_user_id) AS distinct_caregiver_count
FROM alerts a
JOIN elderly_profiles p
    ON p.id = a.elderly_profile_id
GROUP BY
    a.elderly_profile_id,
    p.display_name,
    a.created_at::date;
