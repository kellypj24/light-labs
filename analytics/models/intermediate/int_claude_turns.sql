{#
    One row per main-loop turn that ran to its end: Claude Code writes a turn_duration
    record when a turn finishes, so the turn started durationMs before it. A turn PJ
    interrupted writes none and is left out.
#}

WITH durations AS (

    SELECT
        record_key,
        session_id,
        project,
        recorded_at,
        CAST(record_duration_ms AS BIGINT) AS duration_ms
    FROM {{ ref('stg_claude_records') }}
    WHERE
        record_subtype = 'turn_duration'
        AND NOT is_subagent
        AND record_duration_ms IS NOT NULL

)

SELECT
    session_id,
    project,
    record_key AS turn_key,
    recorded_at AS ended_at,
    recorded_at - TO_MILLISECONDS(duration_ms) AS started_at,
    duration_ms / 1000 AS duration_seconds
FROM durations
