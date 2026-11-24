{#
    One row per planned item with how much of it PJ ticked in the Workouts app. Strong
    and Health stay the record of what was trained; this adds the items they don't
    capture (is_lift FALSE: bag rounds, a ride's parts) and how the app was used.
    A check counts when it is the newest tap for its set, the plan still has the item,
    and the set number is within it. It is in the slot from 30 minutes before the
    planned start to 60 after the planned end.
#}

WITH items AS (

    -- The app keys by item_key, so two items with one label on a day share their checks.
    SELECT *
    FROM {{ ref('stg_training_plan_items') }}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY plan_date, item_key
        ORDER BY item_index
    ) = 1

),

plan_days AS (

    SELECT
        plan_date,
        plan_week,
        plan_date + CAST(slot_start AS TIME) AS slot_start_at,
        plan_date + CAST(slot_end AS TIME) AS slot_end_at
    FROM {{ ref('stg_training_plan_days') }}

),

checked AS (

    SELECT *
    FROM {{ ref('stg_training_checks') }}
    WHERE is_latest AND is_done

),

item_checks AS (

    SELECT
        items.plan_item_id,
        COUNT(*) AS units_checked,
        COUNT(*) FILTER (
            WHERE
            checked.checked_at
            BETWEEN plan_days.slot_start_at - INTERVAL 30 MINUTE
            AND plan_days.slot_end_at + INTERVAL 60 MINUTE
        ) AS units_checked_in_slot,
        MIN(checked.checked_at) AS first_checked_at,
        MAX(checked.checked_at) AS last_checked_at
    FROM items
    INNER JOIN checked
        ON
            items.plan_date = checked.plan_date
            AND items.item_key = checked.item_key
            AND items.unit_count >= checked.set_number
    INNER JOIN plan_days
        ON items.plan_date = plan_days.plan_date
    GROUP BY items.plan_item_id

)

SELECT
    items.plan_item_id,
    items.plan_date,
    plan_days.plan_week,
    items.iso_week,
    items.item_key,
    items.label,
    items.is_lift,
    items.unit_count,
    item_checks.first_checked_at,
    item_checks.last_checked_at,
    COALESCE(item_checks.units_checked, 0) AS units_checked,
    COALESCE(item_checks.units_checked_in_slot, 0) AS units_checked_in_slot,
    COALESCE(item_checks.units_checked, 0) = items.unit_count AS is_checked
FROM items
INNER JOIN plan_days
    ON items.plan_date = plan_days.plan_date
LEFT JOIN item_checks
    ON items.plan_item_id = item_checks.plan_item_id
