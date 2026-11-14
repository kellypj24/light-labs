{#
    One row per day of each weekly plan, as it stood when that day was last planned
    (a midweek replan rewrites the days from its start).
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'training_plan_days') }}

),

renamed AS (

    SELECT
        plan_date,
        iso_week,
        is_rest,
        slot_start,
        slot_end,
        session_type,
        title,
        is_outdoor,
        item_count,
        planned_at,
        source_file,
        CAST(DATE_TRUNC('week', plan_date) AS DATE) AS plan_week,
        NOT is_rest AS is_training,
        DATE_DIFF('minute', CAST(slot_start AS TIME), CAST(slot_end AS TIME)) AS planned_minutes
    FROM source

)

SELECT * FROM renamed
