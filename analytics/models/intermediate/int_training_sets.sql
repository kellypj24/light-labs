{#
    One row per Strong set with its movement pattern (seed `strong_exercises`), the
    weight that counts as load, tonnage and an Epley e1RM.

    Strong logs dumbbell weight per hand. `implements` (seed) is how many are lifted, 2
    for most dumbbell lifts, so tonnage counts both; added_weight and e1RM stay per hand,
    the number PJ sets the PowerBlocks to. A bodyweight lift (pull up,
    dip) logged at or above `training_bodyweight_threshold_lb` logged PJ's bodyweight:
    its added weight is 0, so it adds no tonnage and progresses on reps. e1RM comes only
    from loaded, non-bodyweight sets of 1 to `training_e1rm_max_reps` reps.
#}

WITH sets AS (

    SELECT *
    FROM {{ ref('stg_strong_sets') }}

),

exercises AS (

    SELECT *
    FROM {{ ref('strong_exercises') }}

),

joined AS (

    SELECT
        sets.set_id,
        sets.workout_id,
        sets.workout_at,
        sets.workout_date,
        sets.workout_name,
        sets.duration_minutes AS workout_minutes,
        sets.exercise,
        sets.set_number,
        sets.set_type,
        sets.is_warmup,
        sets.weight AS logged_weight,
        sets.reps,
        exercises.movement_pattern,
        CAST(DATE_TRUNC('week', sets.workout_date) AS DATE) AS workout_week,
        COALESCE(exercises.is_bodyweight_lift, FALSE) AS is_bodyweight_lift,
        COALESCE(exercises.implements, 1) AS implements
    FROM sets
    LEFT JOIN exercises
        ON sets.exercise = exercises.exercise

),

loaded AS (

    SELECT
        *,
        is_bodyweight_lift
        AND COALESCE(logged_weight, 0) >= {{ var('training_bodyweight_threshold_lb') }}
            AS is_logged_bodyweight,
        CASE
            WHEN
                is_bodyweight_lift
                AND COALESCE(logged_weight, 0)
                >= {{ var('training_bodyweight_threshold_lb') }}
                THEN 0
            ELSE COALESCE(logged_weight, 0)
        END AS added_weight
    FROM joined

)

SELECT
    *,
    CASE
        WHEN is_warmup THEN 0
        ELSE added_weight * implements * COALESCE(reps, 0)
    END AS tonnage,
    CASE
        WHEN
            NOT is_warmup
            AND NOT is_bodyweight_lift
            AND added_weight > 0
            AND reps BETWEEN 1 AND {{ var('training_e1rm_max_reps') }}
            THEN added_weight * (1 + reps / 30.0)
    END AS e1rm
FROM loaded
