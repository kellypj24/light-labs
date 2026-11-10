{#
    Weekly volume by movement pattern (Strong) and by cardio type (Health): one row per
    ISO week, category type and category. Weeks without any appear in mart_training_weekly
    only.
#}

WITH lifting AS (

    SELECT
        workout_week AS week_start,
        'movement_pattern' AS category_type,
        movement_pattern AS category,
        COUNT(DISTINCT workout_id) AS session_count,
        COUNT(*) FILTER (WHERE NOT is_warmup) AS working_sets,
        SUM(tonnage) AS tonnage_lb,
        CAST(NULL AS DOUBLE) AS minutes,
        CAST(NULL AS DOUBLE) AS miles
    FROM {{ ref('int_training_sets') }}
    GROUP BY workout_week, movement_pattern

),

cardio AS (

    SELECT
        session_week AS week_start,
        'cardio' AS category_type,
        kind AS category,
        COUNT(*) AS session_count,
        CAST(NULL AS BIGINT) AS working_sets,
        CAST(NULL AS DOUBLE) AS tonnage_lb,
        SUM(duration_minutes) AS minutes,
        SUM(distance_miles) AS miles
    FROM {{ ref('int_training_sessions') }}
    WHERE session_source = 'health'
    GROUP BY session_week, kind

),

unioned AS (

    SELECT * FROM lifting
    UNION ALL BY NAME
    SELECT * FROM cardio

)

SELECT
    *,
    CAST(week_start AS VARCHAR) || '|' || category_type || '|' || category AS breakdown_key
FROM unioned
