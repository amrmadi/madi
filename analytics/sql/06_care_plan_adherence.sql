-- ============================================================================
-- v_care_plan_adherence
--
-- One row per (elderly_profile_id, care_plan_id, care_plan_item_id): does the
-- active, actionable item of an active care plan have at least one matching
-- positive outcome?
--
--   "Positive outcome" means
--     * a medication item -> at least one 'taken' dose log for the schedule
--       the item points at, and
--     * a check-in item   -> at least one 'taken' check-in for the schedule
--       the item points at.
--
-- This is the row-level form of the "care-plan adherence rate" KPI: the
-- numerator is the count of rows where `has_positive_outcome` is TRUE, the
-- denominator is the count of rows in the view.
--
-- Which items are in the view, and why
-- ------------------------------------
-- Only items that can actually be measured are included:
--   * `care_plans.status = 'active'`   - a draft or finished plan is not
--     something anybody is expected to be following today.
--   * `care_plan_items.is_active`       - a deactivated item is off the plan.
--   * `item_kind IN ('medication', 'checkin')`
--     - 'note' items are documentation, not an action that can be adhered to,
--       and 'reminder' items have no occurrence log yet, so neither of them
--       can produce a measured outcome. Including them would silently deflate
--       the rate. The API-side KPI service excludes them and reports how many
--       were excluded; this view simply does not contain them.
--
-- Honest limits
-- --------------
-- * There is no date window here: `has_positive_outcome` means "at least once,
--   ever". A plan item followed for a year and then abandoned still reads as
--   TRUE. Use the API KPI (which takes an explicit window) for time-boxed
--   reporting.
-- * This is not medical advice and it is not a judgement about the resident.
--   It reports whether the workflow happened.
-- ============================================================================

DROP VIEW IF EXISTS v_care_plan_adherence;

CREATE OR REPLACE VIEW v_care_plan_adherence AS
SELECT
    cp.elderly_profile_id,
    p.display_name AS elderly_profile_display_name,
    cp.id AS care_plan_id,
    cp.title AS care_plan_title,
    cp.status AS care_plan_status,
    cpi.id AS care_plan_item_id,
    cpi.item_kind,
    cpi.title AS care_plan_item_title,
    cpi.is_active AS item_is_active,

    -- The measured outcome: at least one matching positive occurrence.
    CASE
        WHEN cpi.item_kind = 'medication'
             AND cpi.medication_schedule_id IS NOT NULL
            THEN EXISTS (
                SELECT 1
                FROM medication_dose_logs mdl
                WHERE mdl.medication_schedule_id = cpi.medication_schedule_id
                  AND mdl.status = 'taken'
            )
        WHEN cpi.item_kind = 'checkin'
             AND cpi.checkin_schedule_id IS NOT NULL
            THEN EXISTS (
                SELECT 1
                FROM checkins c
                WHERE c.checkin_schedule_id = cpi.checkin_schedule_id
                  AND c.status = 'taken'
            )
        ELSE FALSE
    END AS has_positive_outcome,

    -- Supporting counts, so a TRUE/FALSE can be seen in context.
    (
        SELECT COUNT(*)
        FROM medication_dose_logs mdl
        WHERE mdl.medication_schedule_id = cpi.medication_schedule_id
          AND mdl.status = 'taken'
    ) AS taken_dose_count,
    (
        SELECT COUNT(*)
        FROM checkins c
        WHERE c.checkin_schedule_id = cpi.checkin_schedule_id
          AND c.status = 'taken'
    ) AS taken_checkin_count
FROM care_plans cp
JOIN elderly_profiles p
    ON p.id = cp.elderly_profile_id
JOIN care_plan_items cpi
    ON cpi.care_plan_id = cp.id
WHERE cp.status = 'active'
  AND cpi.is_active
  AND cpi.item_kind IN ('medication', 'checkin');
