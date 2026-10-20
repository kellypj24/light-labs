{#
    One row per tool call: the tool_use block from the assistant's message, joined to
    the tool_result that answered it. Duration is call to result, so it includes time
    waiting on a permission prompt. A call with no result was interrupted or is still
    running. Its project is the one it touched (a file path, or a shell command's `cd`
    or `-C` target), else the shell's working directory, which follows any earlier cd.
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
        project AS cwd_project,
        recorded_at AS called_at,
        block ->> '$.id' AS tool_use_id,
        block ->> '$.name' AS tool_name,
        block -> '$.input' AS tool_input,
        TRIM(
            COALESCE(
                block ->> '$.input.file_path',
                block ->> '$.input.notebook_path',
                block ->> '$.input.path',
                NULLIF(
                    REGEXP_EXTRACT(
                        block ->> '$.input.command', '(^|[;&|]\s*)cd\s+([^\s;&|]+)', 2
                    ),
                    ''
                ),
                NULLIF(
                    REGEXP_EXTRACT(block ->> '$.input.command', '\s-C\s+([^\s;&|]+)', 1), ''
                )
            ),
            '"'''
        ) AS touched_path,
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

),

touched AS (

    SELECT
        *,
        {{ claude_folder('touched_path') }} AS touched_folder
    FROM calls
    WHERE call_number = 1

),

-- Every folder seen, as a working directory or as a path a call touched.
folders AS (

    SELECT folder
    FROM {{ ref('stg_claude_records') }}
    WHERE folder IS NOT NULL
    UNION
    SELECT touched_folder AS folder
    FROM touched
    WHERE touched_folder IS NOT NULL

),

-- As staging folds them: a worktree folder <repo>-<topic> counts as <repo>.
folded AS (

    SELECT
        folders.folder,
        COALESCE(ARG_MAX(repos.folder, LENGTH(repos.folder)), folders.folder) AS project
    FROM folders
    LEFT JOIN folders AS repos
        ON STARTS_WITH(folders.folder, repos.folder || '-')
    GROUP BY folders.folder

)

SELECT
    touched.tool_use_id,
    touched.session_id,
    touched.agent_id,
    touched.is_subagent,
    touched.tool_name,
    touched.tool_input,
    touched.touched_path,
    touched.called_at,
    tool_results.returned_at,
    COALESCE(folded.project, touched.touched_folder, touched.cwd_project) AS project,
    touched.tool_input ->> '$.command' AS bash_command,
    touched.tool_input ->> '$.skill' AS skill_name,
    touched.tool_input ->> '$.subagent_type' AS subagent_type,
    -- The same categories as the visual-recap mod's band.
    CASE
        WHEN
            touched.tool_name IN (
                'Read', 'Grep', 'Glob', 'LS', 'NotebookRead', 'LSP', 'ToolSearch'
            )
            THEN 'reading'
        WHEN touched.tool_name IN ('Edit', 'Write', 'MultiEdit', 'NotebookEdit') THEN 'editing'
        WHEN touched.tool_name IN ('Bash', 'BashOutput', 'KillShell', 'PowerShell', 'Monitor')
            THEN 'shell'
        WHEN
            touched.tool_name IN ('WebFetch', 'WebSearch')
            OR STARTS_WITH(touched.tool_name, 'mcp__claude-in-chrome')
            THEN 'web'
        WHEN touched.tool_name IN ('Agent', 'Task', 'SendMessage') THEN 'subagents'
        WHEN touched.tool_name IN ('AskUserQuestion', 'ExitPlanMode') THEN 'asking'
        ELSE 'other'
    END AS activity,
    STARTS_WITH(touched.tool_name, 'mcp__') AS is_mcp,
    SPLIT_PART(touched.tool_name, '__', 2) AS mcp_server,
    tool_results.tool_use_id IS NOT NULL AS is_answered,
    COALESCE(tool_results.is_error, FALSE) AS is_error,
    EPOCH(tool_results.returned_at) - EPOCH(touched.called_at) AS duration_seconds
FROM touched
LEFT JOIN tool_results
    ON
        touched.tool_use_id = tool_results.tool_use_id
        AND tool_results.result_number = 1
LEFT JOIN folded ON touched.touched_folder = folded.folder
