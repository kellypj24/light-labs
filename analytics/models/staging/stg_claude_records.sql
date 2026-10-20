{#
    One row per transcript record: the fields every record type shares, plus the
    message's id, model, content and token usage where it has one. An assistant message
    is written as one record per content block, each repeating the message's usage;
    int_claude_api_calls counts it once.
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'claude_records') }}

),

renamed AS (

    SELECT
        record_key,
        project_dir,
        transcript,
        line_no,
        CAST(record ->> '$.timestamp' AS TIMESTAMPTZ) AS recorded_at,
        CAST(record ->> '$.message.usage.input_tokens' AS BIGINT) AS input_tokens,
        CAST(record ->> '$.message.usage.output_tokens' AS BIGINT) AS output_tokens,
        CAST(record ->> '$.message.usage.cache_read_input_tokens' AS BIGINT)
            AS cache_read_tokens,
        CAST(record ->> '$.message.usage.cache_creation_input_tokens' AS BIGINT)
            AS cache_write_tokens,
        record ->> '$.type' AS record_type,
        record ->> '$.subtype' AS record_subtype,
        record ->> '$.uuid' AS record_uuid,
        record ->> '$.agentId' AS agent_id,
        record ->> '$.cwd' AS cwd,
        record ->> '$.gitBranch' AS git_branch,
        record ->> '$.version' AS claude_version,
        record ->> '$.durationMs' AS record_duration_ms,
        record ->> '$.message.id' AS message_id,
        record ->> '$.message.model' AS model_id,
        record -> '$.message.content' AS message_content,
        COALESCE(record ->> '$.sessionId', record ->> '$.parentSessionId') AS session_id,
        transcript LIKE '%/subagents/%' AS is_subagent,
        -- `cwd` follows the shell's cd, so a subfolder counts as its top-level folder.
        {{ claude_folder("record ->> '$.cwd'") }} AS folder,
        -- A prompt typed by PJ: plain text from a person, not a tool result, a
        -- slash command's expansion or a subagent's brief. Older records have no origin.
        COALESCE(
            (record ->> '$.type') = 'user'
            AND JSON_TYPE(record -> '$.message.content') = 'VARCHAR'
            AND COALESCE(record ->> '$.origin.kind', 'human') = 'human'
            AND NOT COALESCE(CAST(record ->> '$.isMeta' AS BOOLEAN), FALSE)
            AND transcript NOT LIKE '%/subagents/%',
            FALSE
        ) AS is_human_prompt
    FROM source

),

-- A worktree folder named <repo>-<topic> beside its repo's folder counts as that repo.
folders AS (

    SELECT DISTINCT folder
    FROM renamed
    WHERE folder IS NOT NULL

),

projects AS (

    SELECT
        folders.folder,
        COALESCE(ARG_MAX(repos.folder, LENGTH(repos.folder)), folders.folder) AS project
    FROM folders
    LEFT JOIN folders AS repos
        ON STARTS_WITH(folders.folder, repos.folder || '-')
    GROUP BY folders.folder

)

SELECT
    renamed.*,
    projects.project
FROM renamed
LEFT JOIN projects ON renamed.folder = projects.folder
