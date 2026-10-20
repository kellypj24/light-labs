{#
    One row per main-loop turn that ran to its end: Claude Code writes a turn_duration
    record when a turn finishes, so the turn started durationMs before it. A turn PJ
    interrupted writes none and is left out. Its project is the one most of its tool
    calls touched, else the shell's working directory at its end.
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

),

turns AS (

    SELECT
        session_id,
        project AS cwd_project,
        record_key AS turn_key,
        recorded_at AS ended_at,
        recorded_at - TO_MILLISECONDS(duration_ms) AS started_at,
        duration_ms / 1000 AS duration_seconds
    FROM durations

),

touched AS (

    SELECT
        turns.turn_key,
        MODE(tools.project) AS project
    FROM turns
    INNER JOIN {{ ref('int_claude_tool_calls') }} AS tools
        ON
            turns.session_id = tools.session_id
            AND turns.started_at <= tools.called_at
            AND turns.ended_at > tools.called_at
    WHERE
        NOT tools.is_subagent
        AND tools.project NOT IN ('home', 'claude-config', 'scratch', 'other')
    GROUP BY turns.turn_key

)

SELECT
    turns.session_id,
    turns.turn_key,
    turns.ended_at,
    turns.started_at,
    turns.duration_seconds,
    COALESCE(touched.project, turns.cwd_project) AS project
FROM turns
LEFT JOIN touched ON turns.turn_key = touched.turn_key
