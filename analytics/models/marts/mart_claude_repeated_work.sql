{#
    One row per kind of work Claude Code repeats: a shell command pattern (the
    command's first word, plus its subcommand when it has one, after any leading
    `cd <dir> &&`), a skill, or a subagent type. Patterns used across many sessions
    and projects are candidates for a new skill or robot.
#}

WITH bash AS (

    SELECT
        session_id,
        project,
        called_at,
        is_error,
        duration_seconds,
        TRIM(REGEXP_REPLACE(bash_command, '^\s*cd\s+\S+\s*&&\s*', '')) AS command
    FROM {{ ref('int_claude_tool_calls') }}
    WHERE tool_name = 'Bash' AND bash_command IS NOT NULL

),

work AS (

    SELECT
        session_id,
        project,
        called_at,
        is_error,
        duration_seconds,
        'bash' AS work_kind,
        CASE
            WHEN REGEXP_MATCHES(SPLIT_PART(command, ' ', 2), '^[a-z][a-z0-9_-]*$')
                THEN SPLIT_PART(command, ' ', 1) || ' ' || SPLIT_PART(command, ' ', 2)
            ELSE SPLIT_PART(command, ' ', 1)
        END AS pattern
    FROM bash

    UNION ALL

    SELECT
        session_id,
        project,
        called_at,
        is_error,
        duration_seconds,
        'skill' AS work_kind,
        skill_name AS pattern
    FROM {{ ref('int_claude_tool_calls') }}
    WHERE tool_name = 'Skill' AND skill_name IS NOT NULL

    UNION ALL

    SELECT
        session_id,
        project,
        called_at,
        is_error,
        duration_seconds,
        'subagent' AS work_kind,
        COALESCE(subagent_type, 'general-purpose') AS pattern
    FROM {{ ref('int_claude_tool_calls') }}
    WHERE tool_name IN ('Agent', 'Task')

)

SELECT
    work_kind,
    pattern,
    work_kind || '|' || pattern AS work_key,
    COUNT(*) AS call_count,
    COUNT(DISTINCT session_id) AS session_count,
    COUNT(DISTINCT project) AS project_count,
    COUNT(DISTINCT CAST(DATE_TRUNC('week', called_at) AS DATE)) AS week_count,
    COUNT(*) FILTER (WHERE is_error) AS error_count,
    SUM(duration_seconds) AS total_seconds,
    MIN(called_at) AS first_used_at,
    MAX(called_at) AS last_used_at
FROM work
WHERE pattern <> ''
GROUP BY work_kind, pattern
