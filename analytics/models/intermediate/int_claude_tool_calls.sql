{#
    One row per tool call: the tool_use block from the assistant's message, joined to
    the tool_result that answered it. Duration is call to result, so it includes time
    waiting on a permission prompt. A call with no result was interrupted or is still
    running.
#}

WITH records AS (

    SELECT
        record_type,
        session_id,
        agent_id,
        is_subagent,
        project,
        recorded_at,
        message_content
    FROM {{ ref('stg_claude_records') }}
    WHERE
        record_type IN ('assistant', 'user')
        AND JSON_TYPE(message_content) = 'ARRAY'

),

blocks AS (

    SELECT
        records.record_type,
        records.session_id,
        records.agent_id,
        records.is_subagent,
        records.project,
        records.recorded_at,
        UNNEST(FROM_JSON(records.message_content, '["JSON"]')) AS block
    FROM records

),

calls AS (

    SELECT
        session_id,
        agent_id,
        is_subagent,
        project,
        recorded_at AS called_at,
        block ->> '$.id' AS tool_use_id,
        block ->> '$.name' AS tool_name,
        block -> '$.input' AS tool_input,
        ROW_NUMBER() OVER (PARTITION BY block ->> '$.id' ORDER BY recorded_at) AS call_number
    FROM blocks
    WHERE
        record_type = 'assistant'
        AND (block ->> '$.type') = 'tool_use'

),

tool_results AS (

    SELECT
        recorded_at AS returned_at,
        block ->> '$.tool_use_id' AS tool_use_id,
        COALESCE(CAST(block ->> '$.is_error' AS BOOLEAN), FALSE) AS is_error,
        ROW_NUMBER() OVER (
            PARTITION BY block ->> '$.tool_use_id' ORDER BY recorded_at
        ) AS result_number
    FROM blocks
    WHERE
        record_type = 'user'
        AND (block ->> '$.type') = 'tool_result'

)

SELECT
    calls.tool_use_id,
    calls.session_id,
    calls.agent_id,
    calls.is_subagent,
    calls.project,
    calls.tool_name,
    calls.tool_input,
    calls.called_at,
    tool_results.returned_at,
    calls.tool_input ->> '$.command' AS bash_command,
    calls.tool_input ->> '$.skill' AS skill_name,
    calls.tool_input ->> '$.subagent_type' AS subagent_type,
    -- The same categories as the visual-recap mod's band.
    CASE
        WHEN calls.tool_name IN ('Read', 'Grep', 'Glob', 'LS', 'NotebookRead', 'LSP', 'ToolSearch')
            THEN 'reading'
        WHEN calls.tool_name IN ('Edit', 'Write', 'MultiEdit', 'NotebookEdit') THEN 'editing'
        WHEN calls.tool_name IN ('Bash', 'BashOutput', 'KillShell', 'PowerShell', 'Monitor')
            THEN 'shell'
        WHEN
            calls.tool_name IN ('WebFetch', 'WebSearch')
            OR STARTS_WITH(calls.tool_name, 'mcp__claude-in-chrome')
            THEN 'web'
        WHEN calls.tool_name IN ('Agent', 'Task', 'SendMessage') THEN 'subagents'
        WHEN calls.tool_name IN ('AskUserQuestion', 'ExitPlanMode') THEN 'asking'
        ELSE 'other'
    END AS activity,
    STARTS_WITH(calls.tool_name, 'mcp__') AS is_mcp,
    SPLIT_PART(calls.tool_name, '__', 2) AS mcp_server,
    tool_results.tool_use_id IS NOT NULL AS is_answered,
    COALESCE(tool_results.is_error, FALSE) AS is_error,
    EPOCH(tool_results.returned_at) - EPOCH(calls.called_at) AS duration_seconds
FROM calls
LEFT JOIN tool_results
    ON
        calls.tool_use_id = tool_results.tool_use_id
        AND tool_results.result_number = 1
WHERE calls.call_number = 1
