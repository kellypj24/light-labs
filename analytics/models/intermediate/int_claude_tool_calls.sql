{#
    One row per tool call: the tool_use block from the assistant's message, joined to
    the tool_result that answered it. Duration is call to result, so it includes time
    waiting on a permission prompt. A call with no result was interrupted or is still
    running. Its project is the one it touched (a file path, or a shell command's `cd`
    or `-C` target), else the shell's working directory, which follows any earlier cd.

    `task_type` says what kind of work the call did, a shell command by what it runs; it is
    how deterministic work (git, GitHub, checks, waiting) shows apart from the model's
    own. The response that made the call is split evenly over the calls it made, so its
    tokens are what Claude spent deciding on this one.
#}

WITH records AS (

    SELECT
        record_type,
        session_id,
        agent_id,
        is_subagent,
        project,
        worktree,
        message_id,
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
        records.worktree,
        records.message_id,
        records.recorded_at,
        UNNEST(FROM_JSON(records.message_content, '["JSON"]')) AS block
    FROM records

),

calls AS (

    SELECT
        session_id,
        agent_id,
        is_subagent,
        message_id,
        project AS cwd_project,
        worktree AS cwd_worktree,
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
        block ->> '$.input.command' AS raw_command,
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

-- A shell command's parts: split at &&, ||, ;, | and newlines, a heredoc's body cut
-- off, each without `do`/`env`-style keywords, `VAR=value` setup or the path of its
-- program (/usr/bin/grep is grep).
parted AS (

    SELECT
        *,
        COALESCE(
            REGEXP_MATCHES(raw_command, '(\.write\(|write_text\(|open\([^)]*[''"][wa])'), FALSE
        ) AS writes_files,
        LIST_FILTER(
            LIST_TRANSFORM(
                STRING_SPLIT_REGEX(
                    REGEXP_REPLACE(raw_command, '(?s)<<-?\s*[''"]?\w+[''"]?.*$', ''),
                    '\s*(&&|\|\||;|\||\n)\s*'
                ),
                part -> REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        TRIM(part),
                        '^((do|then|else|time|env|sudo|exec|!)\s+'
                        || '|[A-Za-z_][A-Za-z0-9_]*=("[^"]*"|''[^'']*''|\$\([^)]*\)|\S*)\s+)+',
                        ''
                    ),
                    '^[^\s/]*/(\S*/)*',
                    ''
                )
            ),
            part -> part <> ''
        ) AS parts
    FROM calls
    WHERE call_number = 1

),

-- The command counts as its highest-ranked part (claude_shell_task).
ranked AS (

    SELECT
        *,
        LIST_MAX(
            LIST_TRANSFORM(
                parts, part -> {{ claude_shell_task('part', 'writes_files') }} || '|' || part
            )
        ) AS main_part
    FROM parted

),

touched AS (

    SELECT
        *,
        {{ claude_folder('touched_path') }} AS touched_folder,
        COUNT(*) OVER (PARTITION BY message_id) AS calls_in_message,
        CASE
            WHEN tool_name IN ('Read', 'Grep', 'Glob', 'LS', 'NotebookRead', 'LSP') THEN 'read'
            WHEN tool_name IN ('Edit', 'Write', 'MultiEdit', 'NotebookEdit') THEN 'edit'
            WHEN
                tool_name IN ('WebFetch', 'WebSearch')
                OR STARTS_WITH(tool_name, 'mcp__claude-in-chrome')
                THEN 'web'
            WHEN tool_name IN ('Agent', 'Task', 'SendMessage') THEN 'agent'
            WHEN tool_name IN ('AskUserQuestion', 'ExitPlanMode') THEN 'ask'
            WHEN tool_name IN ('BashOutput', 'Monitor', 'TaskStop', 'KillShell') THEN 'wait'
            WHEN STARTS_WITH(tool_name, 'mcp__') THEN 'mcp'
            WHEN tool_name <> 'Bash' OR main_part IS NULL THEN 'other'
            ELSE SPLIT_PART(main_part, '|', 2)
        END AS task_type,
        SPLIT_PART(main_part, '|', 3) AS command
    FROM ranked

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
    touched.message_id,
    touched.tool_name,
    touched.tool_input,
    touched.touched_path,
    touched.command,
    touched.task_type,
    touched.called_at,
    tool_results.returned_at,
    COALESCE(folded.project, touched.touched_folder, touched.cwd_project) AS project,
    CASE
        WHEN touched.touched_folder IS NOT NULL THEN {{ claude_worktree('touched.touched_path') }}
        ELSE touched.cwd_worktree
    END AS worktree,
    touched.tool_input ->> '$.command' AS bash_command,
    touched.tool_input ->> '$.skill' AS skill_name,
    touched.tool_input ->> '$.subagent_type' AS subagent_type,
    -- The visual-recap band's categories, with shell reads and edits counted as such.
    CASE
        WHEN touched.task_type = 'read' THEN 'reading'
        WHEN touched.task_type IN ('edit', 'files') THEN 'editing'
        WHEN touched.task_type = 'web' THEN 'web'
        WHEN touched.task_type = 'agent' THEN 'subagents'
        WHEN touched.task_type = 'ask' THEN 'asking'
        WHEN touched.tool_name IN ('Bash', 'BashOutput', 'KillShell', 'Monitor') THEN 'shell'
        ELSE 'other'
    END AS activity,
    STARTS_WITH(touched.tool_name, 'mcp__') AS is_mcp,
    SPLIT_PART(touched.tool_name, '__', 2) AS mcp_server,
    tool_results.tool_use_id IS NOT NULL AS is_answered,
    COALESCE(tool_results.is_error, FALSE) AS is_error,
    EPOCH(tool_results.returned_at) - EPOCH(touched.called_at) AS duration_seconds,
    api_calls.output_tokens / touched.calls_in_message AS output_tokens,
    (api_calls.input_tokens + api_calls.cache_read_tokens + api_calls.cache_write_tokens)
    / touched.calls_in_message AS context_tokens
FROM touched
LEFT JOIN tool_results
    ON
        touched.tool_use_id = tool_results.tool_use_id
        AND tool_results.result_number = 1
LEFT JOIN folded ON touched.touched_folder = folded.folder
LEFT JOIN {{ ref('int_claude_api_calls') }} AS api_calls
    ON touched.message_id = api_calls.message_id
