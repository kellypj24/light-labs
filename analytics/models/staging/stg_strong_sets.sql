{#
    One row per logged set from Strong. Bodyweight exercises log a weight of 0; their
    tonnage is 0 and they progress on reps. `workout_at` is the phone's local time, and
    a workout's sets all share it, so it identifies the workout.
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'strong_sets') }}

),

renamed AS (

    SELECT
        set_id,
        workout_at,
        workout_name,
        duration_minutes,
        exercise,
        set_number,
        set_type,
        weight,
        unit,
        reps,
        rpe,
        notes,
        workout_notes,
        exported_on,
        source_file,
        CAST(workout_at AS DATE) AS workout_date,
        MD5(CAST(workout_at AS VARCHAR) || '|' || workout_name) AS workout_id,
        COALESCE(weight, 0) = 0 AS is_bodyweight,
        set_type = 'warmup' AS is_warmup,
        COALESCE(weight, 0) * COALESCE(reps, 0) AS tonnage
    FROM source

)

SELECT * FROM renamed
