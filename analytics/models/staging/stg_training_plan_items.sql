{#
    One row per item of each planned day: a lift with its sets, or a line of text (a
    ride, a run, bag rounds). item_key and unit_count are what the Workouts app keys and
    counts its buttons by.
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'training_plan_items') }}

),

renamed AS (

    SELECT
        plan_date,
        item_index,
        iso_week,
        item_key,
        label,
        exercise,
        sets,
        reps,
        load_lb,
        unit_count,
        CAST(plan_date AS VARCHAR) || '-' || CAST(item_index AS VARCHAR) AS plan_item_id,
        exercise IS NOT NULL AS is_lift
    FROM source

)

SELECT * FROM renamed
