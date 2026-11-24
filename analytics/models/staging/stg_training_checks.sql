{#
    One row per tap in the Workouts app, undoings included. The newest row for a
    (plan_date, item_key, set_number) is that set's state.
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'training_checks') }}

),

renamed AS (

    SELECT
        line_index,
        checked_at,
        plan_date,
        item_key,
        set_number,
        is_done,
        CAST(checked_at AS DATE) = plan_date AS is_same_day,
        ROW_NUMBER() OVER (
            PARTITION BY plan_date, item_key, set_number
            ORDER BY line_index DESC
        ) = 1 AS is_latest
    FROM source

)

SELECT * FROM renamed
