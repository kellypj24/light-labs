{#
    One row per Health workout, with three flags the marts filter on:
    - is_fragment: under 3 minutes, an accidental start.
    - is_implausible_pace: slower than 20 min/km, a recording that ran past its end
      (a 5.8 km run logged as 23 hours). Its time is wrong; its distance may not be.
    - is_duplicate: another workout of the same type starts within 10 minutes and is
      the better record (has heart rate, plausible pace, then shorter, then uuid).
    is_counted is what a session mart should count.
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'health_workouts') }}

),

renamed AS (

    SELECT
        workout_uuid,
        activity_type,
        started_at,
        ended_at,
        duration_seconds,
        is_indoor,
        source AS source_app,
        distance_m,
        energy_kcal,
        heart_rate_avg,
        heart_rate_max,
        event_count,
        statistics,
        exported_at,
        source_file,
        CAST(started_at AS DATE) AS workout_date,
        duration_seconds / 60.0 AS duration_minutes,
        distance_m / 1609.344 AS distance_miles,
        heart_rate_avg IS NOT NULL AS has_heart_rate,
        duration_seconds < 180 AS is_fragment,
        CASE
            WHEN distance_m > 0
                THEN (duration_seconds / 60.0) / (distance_m / 1000.0)
        END AS pace_min_per_km,
        COALESCE(
            distance_m > 0 AND (duration_seconds / 60.0) / (distance_m / 1000.0) > 20,
            FALSE
        ) AS is_implausible_pace
    FROM source

),

duplicates AS (

    -- The worse record of a pair: no heart rate where the other has it, then broken
    -- pace where the other's is plausible, then longer, then the higher uuid.
    SELECT DISTINCT worse.workout_uuid
    FROM renamed AS worse
    INNER JOIN renamed AS better
        ON
            worse.activity_type = better.activity_type
            AND worse.workout_uuid <> better.workout_uuid
            AND ABS(DATE_DIFF('second', worse.started_at, better.started_at)) <= 600
            AND NOT worse.is_fragment
            AND NOT better.is_fragment
            AND (
                (NOT worse.has_heart_rate AND better.has_heart_rate)
                OR (
                    worse.has_heart_rate = better.has_heart_rate
                    AND worse.is_implausible_pace
                    AND NOT better.is_implausible_pace
                )
                OR (
                    worse.has_heart_rate = better.has_heart_rate
                    AND worse.is_implausible_pace = better.is_implausible_pace
                    AND (
                        worse.duration_seconds > better.duration_seconds
                        OR (
                            worse.duration_seconds = better.duration_seconds
                            AND worse.workout_uuid > better.workout_uuid
                        )
                    )
                )
            )

),

final AS (

    SELECT
        renamed.*,
        duplicates.workout_uuid IS NOT NULL AS is_duplicate,
        NOT renamed.is_fragment
        AND NOT renamed.is_implausible_pace
        AND duplicates.workout_uuid IS NULL AS is_counted
    FROM renamed
    LEFT JOIN duplicates
        ON renamed.workout_uuid = duplicates.workout_uuid

)

SELECT * FROM final
