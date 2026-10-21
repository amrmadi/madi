-- ============================================================================
-- v_resident_activity_summary
--
-- One row per (elderly_profile_id, day): everything that was observed for a
-- resident that day, from all four event tables at once.
--
--   activity_events  -> what the resident was doing
--   fall_events      -> falls that were detected (or reported)
--   anomaly_events   -> deviations from the resident's own baseline
--   risk_events      -> computed risk observations
--
-- The four tables have different time columns and different shapes, so they
-- are normalised into one stream first and then aggregated per day.
--
-- The column that keeps this project honest
-- -----------------------------------------
-- `simulated_event_count` and `non_simulated_event_count` split every event by
-- its `source`. The `source` vocabulary is fixed by the CHECK constraints:
--
--   'simulated'        demo data written by the seed script
--   'sensor'           a reading from a real device
--   'manual_entry'     typed in by a person
--   'imported_dataset' public research data (other people's recordings)
--   'model'            produced by a model
--
-- So a reader can always tell demo data apart from real readings, and a
-- dashboard that mixes the two can be spotted. `imported_dataset_event_count`
-- is broken out separately because research data is not a measurement of
-- *this* resident either.
--
-- Honest limits
-- --------------
-- * The day each event belongs to is taken from the column that describes the
--   event itself: `started_at` for activity, `occurred_at` for falls and
--   anomalies, `assessed_at` for risk.
-- * `average_anomaly_score` and `average_risk_score` are averages over the
--   events of that day. They are only as comparable as the detector that
--   produced them, which is why `anomaly_type` and the model run are recorded
--   on the events themselves.
-- * An empty day produces no row. This view does not invent a zero row for
--   every resident and every day.
-- ============================================================================

DROP VIEW IF EXISTS v_resident_activity_summary;

CREATE OR REPLACE VIEW v_resident_activity_summary AS
WITH event_stream AS (
    -- Activity: what the resident was doing.
    SELECT
        ae.elderly_profile_id,
        ae.started_at::date AS event_day,
        'activity' AS event_family,
        ae.activity_type AS activity_type,
        ae.source AS source,
        NULL::boolean AS was_verified,
        NULL::double precision AS score,
        1 AS event_count
    FROM activity_events ae

    UNION ALL

    -- Falls: detected by the model, or reported by a person.
    SELECT
        fe.elderly_profile_id,
        fe.occurred_at::date AS event_day,
        'fall' AS event_family,
        NULL::varchar AS activity_type,
        fe.source AS source,
        fe.was_verified AS was_verified,
        NULL::double precision AS score,
        1 AS event_count
    FROM fall_events fe

    UNION ALL

    -- Anomalies: deviations from the resident's own baseline.
    SELECT
        an.elderly_profile_id,
        an.occurred_at::date AS event_day,
        'anomaly' AS event_family,
        NULL::varchar AS activity_type,
        an.source AS source,
        an.was_verified AS was_verified,
        an.score AS score,
        1 AS event_count
    FROM anomaly_events an

    UNION ALL

    -- Risk: a computed level rather than a moment.
    SELECT
        re.elderly_profile_id,
        re.assessed_at::date AS event_day,
        'risk' AS event_family,
        NULL::varchar AS activity_type,
        re.source AS source,
        NULL::boolean AS was_verified,
        re.score AS score,
        1 AS event_count
    FROM risk_events re
)
SELECT
    es.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    es.event_day,

    -- Activity events
    SUM(es.event_count) FILTER (WHERE es.event_family = 'activity') AS total_activity_events,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'walking'
    ) AS walking_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'standing'
    ) AS standing_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'sitting'
    ) AS sitting_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'lying'
    ) AS lying_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'eating'
    ) AS eating_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'sleeping'
    ) AS sleeping_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'toileting'
    ) AS toileting_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'activity' AND es.activity_type = 'unknown'
    ) AS unknown_activity_event_count,

    -- Falls. `verified_fall_event_count` counts the falls a human confirmed;
    -- a detector produces false positives, so the two are kept apart.
    SUM(es.event_count) FILTER (WHERE es.event_family = 'fall') AS fall_event_count,
    SUM(es.event_count) FILTER (
        WHERE es.event_family = 'fall' AND es.was_verified
    ) AS verified_fall_event_count,

    -- Anomalies
    SUM(es.event_count) FILTER (WHERE es.event_family = 'anomaly') AS anomaly_event_count,
    AVG(es.score) FILTER (WHERE es.event_family = 'anomaly') AS average_anomaly_score,

    -- Risk
    SUM(es.event_count) FILTER (WHERE es.event_family = 'risk') AS risk_event_count,
    AVG(es.score) FILTER (WHERE es.event_family = 'risk') AS average_risk_score,

    -- Provenance: demo data versus real readings.
    SUM(es.event_count) FILTER (WHERE es.source = 'simulated') AS simulated_event_count,
    SUM(es.event_count) FILTER (WHERE es.source = 'imported_dataset') AS imported_dataset_event_count,
    SUM(es.event_count) FILTER (WHERE es.source <> 'simulated') AS non_simulated_event_count,

    -- Totals
    SUM(es.event_count) AS total_event_count,
    (
        SUM(es.event_count) FILTER (WHERE es.source <> 'simulated')
        = 0
    ) AS all_events_simulated
FROM event_stream es
JOIN elderly_profiles p
    ON p.id = es.elderly_profile_id
GROUP BY
    es.elderly_profile_id,
    p.display_name,
    es.event_day;
