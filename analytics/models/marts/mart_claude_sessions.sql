{#
    One row per Claude Code session: where and when it ran, how many prompts PJ typed,
    and what it cost in API calls, tokens and tool calls, subagents included. The cache
    hit rate is the share of input tokens served from the prompt cache.
#}

WITH records AS (

    SELECT
        session_id,
        MIN(recorded_at) AS started_at,
        MAX(recorded_at) AS ended_at,
        MODE(project) AS cwd_project,
        ARG_MIN(git_branch, recorded_at) AS git_branch,
        MAX(claude_version) AS claude_version,
        COUNT(*) FILTER (WHERE is_human_prompt) AS prompt_count,
        COUNT(DISTINCT agent_id) AS subagent_count
    FROM {{ ref('stg_claude_records') }}
    WHERE session_id IS NOT NULL AND recorded_at IS NOT NULL
    GROUP BY session_id

),

api_calls AS (

    SELECT
        session_id,
        MODE(model_id) AS model_id,
        COUNT(*) AS api_call_count,
        SUM(input_tokens) AS input_tokens,
        SUM(output_tokens) AS output_tokens,
        SUM(cache_read_tokens) AS cache_read_tokens,
        SUM(cache_write_tokens) AS cache_write_tokens
    FROM {{ ref('int_claude_api_calls') }}
    GROUP BY session_id

),

tool_calls AS (

    SELECT
        session_id,
        COUNT(*) AS tool_call_count,
        COUNT(*) FILTER (WHERE is_error) AS tool_error_count,
        -- Where the session worked: a session started from the home directory belongs
        -- to the repos its tools touched.
        MODE(project) FILTER (
            WHERE project NOT IN ('home', 'claude-config', 'scratch', 'other')
        ) AS project
    FROM {{ ref('int_claude_tool_calls') }}
    GROUP BY session_id

)

SELECT
    records.session_id,
    COALESCE(tool_calls.project, records.cwd_project) AS project,
    records.git_branch,
    records.claude_version,
    api_calls.model_id,
    records.started_at,
    records.ended_at,
    records.prompt_count,
    records.subagent_count,
    EPOCH(records.ended_at) - EPOCH(records.started_at) AS span_seconds,
    COALESCE(api_calls.api_call_count, 0) AS api_call_count,
    COALESCE(tool_calls.tool_call_count, 0) AS tool_call_count,
    COALESCE(tool_calls.tool_error_count, 0) AS tool_error_count,
    COALESCE(api_calls.input_tokens, 0) AS input_tokens,
    COALESCE(api_calls.output_tokens, 0) AS output_tokens,
    COALESCE(api_calls.cache_read_tokens, 0) AS cache_read_tokens,
    COALESCE(api_calls.cache_write_tokens, 0) AS cache_write_tokens,
    {{ safe_divide(
        'api_calls.cache_read_tokens',
        '(api_calls.input_tokens + api_calls.cache_read_tokens + api_calls.cache_write_tokens)'
    ) }} AS cache_hit_rate
FROM records
LEFT JOIN api_calls ON records.session_id = api_calls.session_id
LEFT JOIN tool_calls ON records.session_id = tool_calls.session_id
