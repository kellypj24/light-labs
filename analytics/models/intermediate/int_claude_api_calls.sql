{#
    One row per API response: the records an assistant message was split into,
    counted once. Synthetic messages (Claude Code's own error stand-ins) are left out.
#}

WITH messages AS (

    SELECT
        message_id,
        session_id,
        agent_id,
        is_subagent,
        project,
        model_id,
        recorded_at,
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_write_tokens,
        ROW_NUMBER() OVER (PARTITION BY message_id ORDER BY recorded_at) AS record_number
    FROM {{ ref('stg_claude_records') }}
    WHERE
        record_type = 'assistant'
        AND message_id IS NOT NULL
        AND model_id <> '<synthetic>'

)

SELECT
    message_id,
    session_id,
    agent_id,
    is_subagent,
    project,
    model_id,
    recorded_at AS called_at,
    COALESCE(input_tokens, 0) AS input_tokens,
    COALESCE(output_tokens, 0) AS output_tokens,
    COALESCE(cache_read_tokens, 0) AS cache_read_tokens,
    COALESCE(cache_write_tokens, 0) AS cache_write_tokens
FROM messages
WHERE record_number = 1
