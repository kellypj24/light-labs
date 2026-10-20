{#
    One row per kind of work Claude Code repeats: a shell command pattern (the
    command's first word, plus its subcommand when it has one, after `cd <dir> &&` and
    `VAR=value;` setup), a skill, or a subagent type. With the tokens Claude spent
    deciding on each call, a pattern used across many sessions, and deterministic by its
    task (git, github, checks, wait, network), is a candidate for a script, tool or robot.
#}

WITH work AS (

    SELECT
        session_id,
        project,
        called_at,
        is_error,
        duration_seconds,
        output_tokens,
        context_tokens,
        task_type,
        'bash' AS work_kind,
        CASE
            WHEN REGEXP_MATCHES(SPLIT_PART(command, ' ', 2), '^[a-z][a-z0-9_-]*$')
                THEN SPLIT_PART(command, ' ', 1) || ' ' || SPLIT_PART(command, ' ', 2)
            ELSE SPLIT_PART(command, ' ', 1)
        END AS pattern
    FROM {{ ref('int_claude_tool_calls') }}
    WHERE tool_name = 'Bash' AND command IS NOT NULL

    UNION ALL

    SELECT
        session_id,
        project,
        called_at,
        is_error,
        duration_seconds,
        output_tokens,
        context_tokens,
        task_type,
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
        output_tokens,
        context_tokens,
        task_type,
        'subagent' AS work_kind,
        COALESCE(subagent_type, 'general-purpose') AS pattern
    FROM {{ ref('int_claude_tool_calls') }}
    WHERE tool_name IN ('Agent', 'Task')

)

SELECT
    work_kind,
    pattern,
    work_kind || '|' || pattern AS work_key,
    MODE(task_type) AS task_type,
    COUNT(*) AS call_count,
    COUNT(DISTINCT session_id) AS session_count,
    COUNT(DISTINCT project) AS project_count,
    COUNT(DISTINCT CAST(DATE_TRUNC('week', called_at) AS DATE)) AS week_count,
    COUNT(*) FILTER (WHERE is_error) AS error_count,
    SUM(duration_seconds) AS total_seconds,
    SUM(output_tokens) AS output_tokens,
    SUM(context_tokens) AS context_tokens,
    MIN(called_at) AS first_used_at,
    MAX(called_at) AS last_used_at
FROM work
WHERE pattern <> ''
GROUP BY work_kind, pattern
