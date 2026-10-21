-- ============================================================================
-- v_alert_acknowledgement_performance
--
-- One row per alert: the raw material behind the "alert acknowledgement rate"
-- and "median time to acknowledge" KPIs.
--
-- How the two KPIs are computed from this view
-- --------------------------------------------
--   acknowledgement rate = COUNT(is_acknowledged) / COUNT(*)
--   median seconds to acknowledge = median(seconds_to_acknowledge)
--                                     over the acknowledged rows only
--
-- The unacknowledged rows stay in this view with `is_acknowledged = false` and
-- `seconds_to_acknowledge = NULL`. They are deliberately *not* dropped here:
-- the API-side KPI service excludes them from the median but reports how many
-- were excluded, because a median computed over the lucky rows alone would
-- look better than reality.
--
-- Honest limits
-- --------------
-- * `seconds_to_acknowledge` is measured from `created_at`, not from the moment
--   the underlying problem happened. If the event was recorded late, the
--   alert appears to have been ignored for longer than it really was.
-- * `acknowledged_by_display_name` is NULL for alerts nobody acknowledged.
--   That NULL is the honest answer, not a missing value to be filled in.
-- * `occurrence_count` says how often the same underlying problem was
--   re-detected and folded into this one alert.
-- ============================================================================

DROP VIEW IF EXISTS v_alert_acknowledgement_performance;

CREATE OR REPLACE VIEW v_alert_acknowledgement_performance AS
SELECT
    a.id AS alert_id,
    a.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    a.alert_type,
    a.severity,
    a.status,
    a.created_at,
    a.acknowledged_at,
    a.resolved_at,

    -- TRUE only when somebody actually acknowledged the alert.
    (a.acknowledged_at IS NOT NULL) AS is_acknowledged,

    -- NULL when the alert was never acknowledged / never resolved.
    EXTRACT(EPOCH FROM (a.acknowledged_at - a.created_at)) AS seconds_to_acknowledge,
    EXTRACT(EPOCH FROM (a.resolved_at - a.created_at)) AS seconds_to_resolve,

    -- How often the same underlying problem was re-detected.
    a.occurrence_count,

    -- Who acknowledged it (LEFT JOIN: an unacknowledged alert has no user).
    a.acknowledged_by_user_id,
    u.display_name AS acknowledged_by_display_name
FROM alerts a
JOIN elderly_profiles p
    ON p.id = a.elderly_profile_id
LEFT JOIN users u
    ON u.id = a.acknowledged_by_user_id;
