{#
    One row per planned ISO week: what the plan asked for against what Strong and
    Health logged, with the notes that explain a gap beside it. A planned day counts
    as completed when any session was logged that date; it is due once the date has
    come.
#}

WITH plan_days AS (

    SELECT *
    FROM {{ ref('stg_training_plan_days') }}

),

session_days AS (

    SELECT
        session_date,
        COUNT(*) AS session_count
    FROM {{ ref('int_training_sessions') }}
    GROUP BY session_date

),

note_days AS (

    SELECT
        note_day,
        COALESCE(BOOL_OR(kind = 'sick'), FALSE) AS is_sick,
        COALESCE(BOOL_OR(kind = 'travel'), FALSE) AS is_away,
        COUNT(*) FILTER (WHERE kind = 'ache') AS ache_notes,
        COALESCE(SUM(minutes) FILTER (WHERE kind = 'chore'), 0) AS chore_minutes
    FROM {{ ref('int_training_note_days') }}
    GROUP BY note_day

),

days AS (

    SELECT
        plan_days.plan_week,
        plan_days.iso_week,
        plan_days.is_training AS is_planned,
        plan_days.plan_date <= CURRENT_DATE AS is_due,
        session_days.session_date IS NOT NULL AS is_trained,
        COALESCE(note_days.is_sick, FALSE) AS is_sick,
        COALESCE(note_days.is_away, FALSE) AS is_away,
        COALESCE(note_days.ache_notes, 0) AS ache_notes,
        COALESCE(note_days.chore_minutes, 0) AS chore_minutes
    FROM plan_days
    LEFT JOIN session_days
        ON plan_days.plan_date = session_days.session_date
    LEFT JOIN note_days
        ON plan_days.plan_date = note_days.note_day

),

weekly AS (

    SELECT
        plan_week AS week_start,
        iso_week,
        COUNT(*) FILTER (WHERE is_planned) AS planned_sessions,
        COUNT(*) FILTER (WHERE is_planned AND is_due) AS due_sessions,
        COUNT(*) FILTER (WHERE is_planned AND is_trained) AS completed_sessions,
        COUNT(*) FILTER (WHERE is_planned AND is_due AND NOT is_trained) AS missed_sessions,
        COUNT(*) FILTER (
            WHERE is_planned AND is_due AND NOT is_trained AND (is_sick OR is_away)
        ) AS missed_sick_or_away,
        COUNT(*) FILTER (WHERE NOT is_planned AND is_trained) AS unplanned_training_days,
        COUNT(*) FILTER (WHERE is_sick) AS sick_days,
        COUNT(*) FILTER (WHERE is_away) AS away_days,
        SUM(ache_notes) AS ache_notes,
        SUM(chore_minutes) AS chore_minutes
    FROM days
    GROUP BY plan_week, iso_week

)

SELECT
    *,
    {{ safe_divide('completed_sessions', 'due_sessions') }} AS adherence_rate
FROM weekly
