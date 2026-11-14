{#
    One row per counted note row per day it covers: a three-day trip is three rows.
    A row's minutes sit on its first day only. No note text here or downstream.
#}

WITH notes AS (

    SELECT *
    FROM {{ ref('stg_training_notes') }}
    WHERE is_counted

),

spans AS (

    SELECT
        note_row_id,
        kind,
        note_date,
        is_done,
        minutes,
        effort,
        UNNEST(GENERATE_SERIES(note_date, last_date, INTERVAL 1 DAY)) AS covered_at
    FROM notes

)

SELECT
    note_row_id,
    kind,
    is_done,
    effort,
    CAST(covered_at AS DATE) AS note_day,
    note_row_id || '-' || STRFTIME(covered_at, '%Y-%m-%d') AS note_day_id,
    CASE WHEN CAST(covered_at AS DATE) = note_date THEN minutes END AS minutes
FROM spans
