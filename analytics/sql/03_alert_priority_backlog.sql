-- ============================================================================
-- v_alert_priority_backlog
--
-- The open-alert backlog, grouped by (elderly_profile_id, severity, alert_type).
--
-- This is the "high-priority alert count" view: filter it to
-- `severity IN ('high', 'critical')` and read `open_alert_count`. The
-- `oldest_open_alert_created_at` column answers the question that actually
-- matters on a care floor — how long has this been sitting here?
--
-- What "open" means
-- -----------------
-- `status IN ('new', 'acknowledged')`: raised but not yet finished. A
-- `resolved` or `dismissed` alert is finished, whatever the outcome was.
--
-- Honest limits
-- --------------
-- * An open alert is not a crisis. It is work that has not been closed yet.
--   A missing measurement is never escalated here.
-- * `oldest_open_alert_created_at` is the age of the *oldest* alert in the
--   group, not an average age, so one neglected alert stays visible instead
--   of being averaged away.
-- * `severity` is an operational triage priority, never a medical risk score.
-- ============================================================================

DROP VIEW IF EXISTS v_alert_priority_backlog;

CREATE OR REPLACE VIEW v_alert_priority_backlog AS
SELECT
    a.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    a.severity,
    a.alert_type,
    COUNT(*) AS open_alert_count,
    MIN(a.created_at) AS oldest_open_alert_created_at,
    MAX(a.created_at) AS newest_open_alert_created_at,
    -- When the first of these alerts was acknowledged, if any of them was.
    MIN(a.acknowledged_at) AS earliest_acknowledged_at
FROM alerts a
JOIN elderly_profiles p
    ON p.id = a.elderly_profile_id
WHERE a.status IN ('new', 'acknowledged')
GROUP BY
    a.elderly_profile_id,
    p.display_name,
    a.severity,
    a.alert_type;
