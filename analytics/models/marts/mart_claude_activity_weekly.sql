{#
    One row per week and project: finished main-loop turns and their working time split
    by activity. A tool's time is call to result; thinking is what is left of the turn.
    Parallel tool calls each count in full, so a turn's tool time is capped at its
    length. Subagents' own tools are left out: the Agent call's time covers them.
#}

WITH tool_time AS (

    SELECT
        turns.turn_key,
        tools.activity,
        SUM(tools.duration_seconds) AS seconds
    FROM {{ ref('int_claude_turns') }} AS turns
    INNER JOIN {{ ref('int_claude_tool_calls') }} AS tools
        ON
            turns.session_id = tools.session_id
            AND turns.started_at <= tools.called_at
            AND turns.ended_at > tools.called_at
    WHERE NOT tools.is_subagent AND tools.duration_seconds IS NOT NULL
    GROUP BY turns.turn_key, tools.activity

),

per_turn AS (

    SELECT
        turn_key,
        SUM(seconds) AS tool_seconds,
        SUM(seconds) FILTER (WHERE activity = 'reading') AS reading_seconds,
        SUM(seconds) FILTER (WHERE activity = 'editing') AS editing_seconds,
        SUM(seconds) FILTER (WHERE activity = 'shell') AS shell_seconds,
        SUM(seconds) FILTER (WHERE activity = 'web') AS web_seconds,
        SUM(seconds) FILTER (WHERE activity = 'subagents') AS subagent_seconds,
        SUM(seconds) FILTER (WHERE activity = 'asking') AS asking_seconds,
        SUM(seconds) FILTER (WHERE activity = 'other') AS other_tool_seconds
    FROM tool_time
    GROUP BY turn_key

),

turns AS (

    SELECT
        turns.project,
        turns.session_id,
        turns.duration_seconds,
        CAST(DATE_TRUNC('week', turns.started_at) AS DATE) AS week_start,
        -- Scales tool time down when parallel calls add up past the turn's length.
        LEAST(1, {{ safe_divide('turns.duration_seconds', 'per_turn.tool_seconds') }})
            AS tool_scale,
        COALESCE(per_turn.tool_seconds, 0) AS tool_seconds,
        COALESCE(per_turn.reading_seconds, 0) AS reading_seconds,
        COALESCE(per_turn.editing_seconds, 0) AS editing_seconds,
        COALESCE(per_turn.shell_seconds, 0) AS shell_seconds,
        COALESCE(per_turn.web_seconds, 0) AS web_seconds,
        COALESCE(per_turn.subagent_seconds, 0) AS subagent_seconds,
        COALESCE(per_turn.asking_seconds, 0) AS asking_seconds,
        COALESCE(per_turn.other_tool_seconds, 0) AS other_tool_seconds
    FROM {{ ref('int_claude_turns') }} AS turns
    LEFT JOIN per_turn ON turns.turn_key = per_turn.turn_key

)

SELECT
    project,
    week_start,
    CAST(week_start AS VARCHAR) || '|' || project AS activity_week_key,
    COUNT(*) AS turn_count,
    COUNT(DISTINCT session_id) AS session_count,
    SUM(duration_seconds) AS working_seconds,
    SUM(GREATEST(0, duration_seconds - tool_seconds)) AS thinking_seconds,
    SUM(reading_seconds * COALESCE(tool_scale, 1)) AS reading_seconds,
    SUM(editing_seconds * COALESCE(tool_scale, 1)) AS editing_seconds,
    SUM(shell_seconds * COALESCE(tool_scale, 1)) AS shell_seconds,
    SUM(web_seconds * COALESCE(tool_scale, 1)) AS web_seconds,
    SUM(subagent_seconds * COALESCE(tool_scale, 1)) AS subagent_seconds,
    SUM(asking_seconds * COALESCE(tool_scale, 1)) AS asking_seconds,
    SUM(other_tool_seconds * COALESCE(tool_scale, 1)) AS other_tool_seconds,
    MEDIAN(duration_seconds) AS median_turn_seconds
FROM turns
GROUP BY project, week_start
