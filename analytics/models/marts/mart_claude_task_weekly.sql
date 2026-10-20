{#
    One row per week, project and task: what Claude Code's tool calls did, how long
    they ran and what Claude spent deciding on them. Deterministic tasks (git, github,
    checks, wait, network, files, services) are work a script or harness could take over; the
    rest needs a model, local or not.
#}

SELECT
    project,
    task_type,
    CAST(DATE_TRUNC('week', called_at) AS DATE) AS week_start,
    CAST(CAST(DATE_TRUNC('week', called_at) AS DATE) AS VARCHAR)
    || '|' || project || '|' || task_type AS task_week_key,
    task_type IN ('git', 'github', 'checks', 'wait', 'network', 'files', 'services')
        AS is_deterministic,
    COUNT(*) AS call_count,
    COUNT(DISTINCT session_id) AS session_count,
    COUNT(*) FILTER (WHERE is_error) AS error_count,
    SUM(duration_seconds) AS total_seconds,
    SUM(output_tokens) AS output_tokens,
    SUM(context_tokens) AS context_tokens
FROM {{ ref('int_claude_tool_calls') }}
GROUP BY project, task_type, CAST(DATE_TRUNC('week', called_at) AS DATE)
