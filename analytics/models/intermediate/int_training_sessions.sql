{#
    One row per training session: each Strong workout, and each counted Health workout
    except strength types (Strong writes its own sessions to Health). Health times are
    UTC; both sources are in local time (`training_timezone`) here.
#}

WITH lifting AS (

    SELECT
        workout_id AS session_id,
        'strong' AS session_source,
        'lifting' AS kind,
        workout_at AS started_at_local,
        workout_date AS session_date,
        workout_week AS session_week,
        MAX(workout_minutes) AS duration_minutes,
        CAST(NULL AS DOUBLE) AS distance_miles,
        COUNT(*) FILTER (WHERE NOT is_warmup) AS set_count,
        SUM(tonnage) AS tonnage,
        FALSE AS has_heart_rate
    FROM {{ ref('int_training_sets') }}
    GROUP BY workout_id, workout_at, workout_date, workout_week

),

health AS (

    SELECT
        workout_uuid AS session_id,
        activity_type AS kind,
        duration_minutes,
        distance_miles,
        has_heart_rate,
        TIMEZONE('{{ var("training_timezone") }}', started_at) AS started_at_local
    FROM {{ ref('stg_health_workouts') }}
    WHERE
        is_counted
        AND activity_type NOT IN (
            {%- for t in var('training_strength_activity_types') %}
                '{{ t }}'{{ "," if not loop.last }}
            {%- endfor %}
        )

),

cardio AS (

    SELECT
        session_id,
        'health' AS session_source,
        kind,
        started_at_local,
        CAST(started_at_local AS DATE) AS session_date,
        CAST(DATE_TRUNC('week', CAST(started_at_local AS DATE)) AS DATE) AS session_week,
        duration_minutes,
        distance_miles,
        CAST(NULL AS BIGINT) AS set_count,
        CAST(NULL AS DOUBLE) AS tonnage,
        has_heart_rate
    FROM health

)

SELECT * FROM lifting
UNION ALL BY NAME
SELECT * FROM cardio
