{#
    One row per thing a note said (an event, a chore, a sick day, ...). Voided notes
    are kept and flagged; is_counted is what the marts read. note_text and what are
    PJ's words: nothing downstream of intermediate selects them.
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'training_notes') }}

),

renamed AS (

    SELECT
        note_id,
        row_index,
        noted_at,
        kind,
        note_date,
        start_time,
        end_time,
        minutes,
        effort,
        is_done,
        what,
        note_text,
        model AS parser_model,
        wants_replan,
        is_voided,
        note_id || '-' || CAST(row_index AS VARCHAR) AS note_row_id,
        COALESCE(end_date, note_date) AS last_date,
        NOT is_voided AS is_counted
    FROM source

)

SELECT * FROM renamed
