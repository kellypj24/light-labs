{#
    One row per exercise and ISO week it was trained: best e1RM, best reps, volume, and
    the top set of the week's last session (heaviest added weight, then most reps).
    Progression starts from that top set. Bodyweight lifts have no e1RM; they progress
    on best_reps. is_latest_week marks each exercise's most recent week.
#}

WITH sets AS (

    SELECT *
    FROM {{ ref('int_training_sets') }}
    WHERE NOT is_warmup

),

weekly AS (

    SELECT
        exercise,
        movement_pattern,
        is_bodyweight_lift,
        workout_week AS week_start,
        COUNT(DISTINCT workout_id) AS session_count,
        COUNT(*) AS working_sets,
        SUM(tonnage) AS tonnage_lb,
        MAX(e1rm) AS best_e1rm,
        MAX(reps) AS best_reps,
        MAX(added_weight) AS max_added_weight,
        MAX(workout_date) AS last_session_date
    FROM sets
    GROUP BY exercise, movement_pattern, is_bodyweight_lift, workout_week

),

last_session_top_set AS (

    SELECT
        exercise,
        workout_week AS week_start,
        added_weight AS top_set_weight,
        reps AS top_set_reps
    FROM sets
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY exercise, workout_week
        ORDER BY workout_at DESC, added_weight DESC, reps DESC, set_number ASC
    ) = 1

)

SELECT
    weekly.exercise,
    weekly.movement_pattern,
    weekly.is_bodyweight_lift,
    weekly.week_start,
    weekly.session_count,
    weekly.working_sets,
    weekly.tonnage_lb,
    weekly.best_e1rm,
    weekly.best_reps,
    weekly.max_added_weight,
    weekly.last_session_date,
    last_session_top_set.top_set_weight,
    last_session_top_set.top_set_reps,
    weekly.exercise || '|' || CAST(weekly.week_start AS VARCHAR) AS lift_week_key,
    weekly.best_e1rm - LAG(weekly.best_e1rm) OVER (
        PARTITION BY weekly.exercise ORDER BY weekly.week_start
    ) AS e1rm_change,
    weekly.week_start = MAX(weekly.week_start) OVER (PARTITION BY weekly.exercise)
        AS is_latest_week
FROM weekly
INNER JOIN last_session_top_set
    ON
        weekly.exercise = last_session_top_set.exercise
        AND weekly.week_start = last_session_top_set.week_start
