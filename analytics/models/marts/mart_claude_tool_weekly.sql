{#
    One row per week, project and tool: how often it was called, how often it failed,
    and how long calls took (call to result, permission prompts included).
#}

WITH calls AS (

    SELECT
        project,
        tool_name,
        session_id,
        is_error,
        duration_seconds,
        CAST(DATE_TRUNC('week', called_at) AS DATE) AS week_start
    FROM {{ ref('int_claude_tool_calls') }}

)

SELECT
    week_start,
    project,
    tool_name,
    CAST(week_start AS VARCHAR) || '|' || project || '|' || tool_name AS tool_week_key,
    COUNT(*) AS call_count,
    COUNT(*) FILTER (WHERE is_error) AS error_count,
    COUNT(DISTINCT session_id) AS session_count,
    {{ safe_divide('COUNT(*) FILTER (WHERE is_error)', 'COUNT(*)') }} AS error_rate,
    SUM(duration_seconds) AS total_seconds,
    MEDIAN(duration_seconds) AS median_seconds
FROM calls
GROUP BY week_start, project, tool_name
