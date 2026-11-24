{#
    One row per planned ISO week: how much of the plan PJ ticked off in the Workouts
    app, and when. Telemetry for the app, and the only count of items Strong and Health
    don't capture. Not a measure of training done: mart_training_adherence has that.
#}

WITH items AS (

    SELECT *
    FROM {{ ref('int_training_checked_items') }}

),

item_days AS (

    SELECT
        plan_date,
        SUM(unit_count) AS planned_units,
        SUM(units_checked) AS checked_units,
        SUM(units_checked_in_slot) AS checked_units_in_slot,
        COUNT(*) FILTER (WHERE NOT is_lift) AS unlogged_items,
        COUNT(*) FILTER (WHERE NOT is_lift AND is_checked) AS unlogged_items_checked
    FROM items
    GROUP BY plan_date

),

tap_days AS (

    SELECT
        plan_date,
        COUNT(*) AS taps,
        COUNT(*) FILTER (WHERE NOT is_done) AS undone_taps
    FROM {{ ref('stg_training_checks') }}
    GROUP BY plan_date

),

weekly AS (

    SELECT
        plan_days.plan_week AS week_start,
        plan_days.iso_week,
        COUNT(*) FILTER (WHERE plan_days.is_training) AS planned_sessions,
        COUNT(*) FILTER (WHERE item_days.checked_units > 0) AS days_used,
        COALESCE(SUM(item_days.planned_units), 0) AS planned_units,
        COALESCE(SUM(item_days.checked_units), 0) AS checked_units,
        COALESCE(SUM(item_days.checked_units_in_slot), 0) AS checked_units_in_slot,
        COALESCE(SUM(item_days.unlogged_items), 0) AS unlogged_items,
        COALESCE(SUM(item_days.unlogged_items_checked), 0) AS unlogged_items_checked,
        COALESCE(SUM(tap_days.taps), 0) AS taps,
        COALESCE(SUM(tap_days.undone_taps), 0) AS undone_taps
    FROM {{ ref('stg_training_plan_days') }} AS plan_days
    LEFT JOIN item_days
        ON plan_days.plan_date = item_days.plan_date
    LEFT JOIN tap_days
        ON plan_days.plan_date = tap_days.plan_date
    GROUP BY plan_days.plan_week, plan_days.iso_week

)

SELECT
    *,
    {{ safe_divide('checked_units', 'planned_units') }} AS checked_share,
    {{ safe_divide('checked_units_in_slot', 'checked_units') }} AS in_slot_share
FROM weekly
