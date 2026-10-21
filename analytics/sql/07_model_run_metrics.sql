-- ============================================================================
-- v_model_run_metrics
--
-- One row per `model_runs` row: what the AI layer actually did, and whether
-- it recorded anything about it.
--
-- This is the row-level form of the "model-run metric coverage" KPI: the
-- numerator is the count of rows where `has_metrics` is TRUE among the
-- finished runs, the denominator is the count of finished runs.
--
-- What is deliberately NOT here
-- -----------------------------
-- * No accuracy, precision, recall or F1 column. Those numbers come from the
--   model evaluation pipeline and are stored in `metrics_json` when they were
--   really measured. This view reports whether `metrics_json` exists
--   (`has_metrics`), never a substitute for it.
-- * `model_runs` rows with `status = 'pending'` or `'running'` have a NULL
--   `finished_at` and therefore a NULL `duration_seconds`. That is the truth:
--   the run has not finished.
--
-- Honest limits
-- --------------
-- * `duration_seconds` measures wall-clock time between `started_at` and
--   `finished_at`. It says nothing about how good the result was.
-- * A failed run is a legitimate, useful record. `has_failed` and
--   `error_message` are exposed so failures are counted rather than hidden.
-- ============================================================================

DROP VIEW IF EXISTS v_model_run_metrics;

CREATE OR REPLACE VIEW v_model_run_metrics AS
SELECT
    mr.id AS model_run_id,
    mr.task,
    mr.model_name,
    mr.model_version,
    mr.status,
    mr.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    mr.started_at,
    mr.finished_at,

    -- NULL while the run has not finished.
    EXTRACT(EPOCH FROM (mr.finished_at - mr.started_at)) AS duration_seconds,

    -- Whether the run recorded metrics. This is coverage, not quality.
    (mr.metrics_json IS NOT NULL) AS has_metrics,

    -- The raw metrics text, exactly as it was written. It is JSON, so a BI
    -- tool has to parse it; it is left as text on purpose so nothing is
    -- flattened into a number that was never measured.
    mr.metrics_json,

    -- Whether the run failed, and why.
    (mr.status = 'failed') AS has_failed,
    mr.error_message
FROM model_runs mr
LEFT JOIN elderly_profiles p
    ON p.id = mr.elderly_profile_id;
