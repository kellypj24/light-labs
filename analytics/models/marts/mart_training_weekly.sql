{#
    One row per ISO week (Monday start, local time) from the first session to this week,
    including weeks without training. Load is minutes: lifting sessions, counted cardio
    (no RPE is logged, and heart rate is on few sessions) and the chores PJ noted with
    a duration, once their day has come (int_training_note_days), minute for minute.

    acute_chronic_ratio is the 7-day minutes over the 28-day weekly average, as of the
    week's last day (today for the current week). The planner deloads above 1.3.
#}

WITH sessions AS (

    SELECT *
    FROM {{ ref('int_training_sessions') }}

),

bounds AS (

    SELECT
        MIN(session_date) AS first_date,
        CURRENT_DATE AS today
    FROM sessions

),

days AS (

    SELECT CAST(UNNEST(GENERATE_SERIES(first_date, today, INTERVAL 1 DAY)) AS DATE) AS load_date
    FROM bounds
    WHERE first_date IS NOT NULL

),

chores AS (

    SELECT
        note_day,
        CAST(DATE_TRUNC('week', note_day) AS DATE) AS chore_week,
        minutes
    FROM {{ ref('int_training_note_days') }}
    WHERE
        kind = 'chore'
        AND minutes IS NOT NULL
        AND note_day <= CURRENT_DATE

),

load_minutes AS (

    SELECT
        session_date AS load_date,
        duration_minutes AS minutes
    FROM sessions
    UNION ALL
    SELECT
        note_day AS load_date,
        minutes
    FROM chores

),

daily_minutes AS (

    SELECT
        load_date AS session_date,
        SUM(minutes) AS minutes
    FROM load_minutes
    GROUP BY load_date

),

weekly_chores AS (

    SELECT
        chore_week,
        SUM(minutes) AS chore_minutes
    FROM chores
    GROUP BY chore_week

),

daily_load AS (

    SELECT
        days.load_date,
        CAST(DATE_TRUNC('week', days.load_date) AS DATE) AS week_start,
        SUM(COALESCE(daily_minutes.minutes, 0)) OVER (
            ORDER BY days.load_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS acute_minutes,
        SUM(COALESCE(daily_minutes.minutes, 0)) OVER (
            ORDER BY days.load_date ROWS BETWEEN 27 PRECEDING AND CURRENT ROW
        ) / 4.0 AS chronic_weekly_minutes
    FROM days
    LEFT JOIN daily_minutes
        ON days.load_date = daily_minutes.session_date

),

week_end_load AS (

    SELECT
        week_start,
        load_date AS load_as_of,
        acute_minutes,
        chronic_weekly_minutes
    FROM daily_load
    QUALIFY ROW_NUMBER() OVER (PARTITION BY week_start ORDER BY load_date DESC) = 1

),

weekly_sessions AS (

    SELECT
        session_week,
        COUNT(*) FILTER (WHERE session_source = 'strong') AS lifting_sessions,
        COALESCE(SUM(duration_minutes) FILTER (WHERE session_source = 'strong'), 0)
            AS lifting_minutes,
        COALESCE(SUM(set_count), 0) AS working_sets,
        COALESCE(SUM(tonnage), 0) AS tonnage_lb,
        COUNT(*) FILTER (WHERE session_source = 'health') AS cardio_sessions,
        COALESCE(SUM(duration_minutes) FILTER (WHERE session_source = 'health'), 0)
            AS cardio_minutes,
        COALESCE(SUM(distance_miles), 0) AS cardio_miles,
        COUNT(DISTINCT session_date) AS training_days
    FROM sessions
    GROUP BY session_week

)

SELECT
    week_end_load.week_start,
    week_end_load.load_as_of,
    week_end_load.acute_minutes,
    week_end_load.chronic_weekly_minutes,
    STRFTIME(week_end_load.week_start, '%G-W%V') AS iso_week,
    COALESCE(weekly_sessions.training_days, 0) AS training_days,
    COALESCE(weekly_sessions.lifting_sessions, 0) AS lifting_sessions,
    COALESCE(weekly_sessions.lifting_minutes, 0) AS lifting_minutes,
    COALESCE(weekly_sessions.working_sets, 0) AS working_sets,
    COALESCE(weekly_sessions.tonnage_lb, 0) AS tonnage_lb,
    COALESCE(weekly_sessions.cardio_sessions, 0) AS cardio_sessions,
    COALESCE(weekly_sessions.cardio_minutes, 0) AS cardio_minutes,
    COALESCE(weekly_sessions.cardio_miles, 0) AS cardio_miles,
    COALESCE(weekly_sessions.lifting_minutes, 0)
    + COALESCE(weekly_sessions.cardio_minutes, 0) AS training_minutes,
    COALESCE(weekly_chores.chore_minutes, 0) AS chore_minutes,
    {{ safe_divide('week_end_load.acute_minutes', 'week_end_load.chronic_weekly_minutes') }}
        AS acute_chronic_ratio
FROM week_end_load
LEFT JOIN weekly_sessions
    ON week_end_load.week_start = weekly_sessions.session_week
LEFT JOIN weekly_chores
    ON week_end_load.week_start = weekly_chores.chore_week
