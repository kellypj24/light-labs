{% macro claude_worktree(path) -%}
    {#-
        The checkout a path is in, relative to the home directory: its top-level folder
        (`light-labs`, or a sibling worktree `light-labs-bar`), or
        `<folder>/.claude/worktrees/<name>` for a worktree nested inside it. NULL where
        claude_folder() gives a bucket or nothing. claude_folder() folds this up to the
        project.
    -#}
    {%- set inner = "(" ~ path ~ ")" %}
    CASE
        WHEN {{ claude_folder(path) }} IN ('home', 'claude-config', 'scratch', 'other') THEN NULL
        WHEN REGEXP_MATCHES(
            {{ inner }}, '^(/(Users|home)/[^/]+|~|\$HOME)/[^/$][^/]*/\.claude/worktrees/[^/]+'
        )
            THEN REGEXP_EXTRACT(
                {{ inner }},
                '^(/(Users|home)/[^/]+|~|\$HOME)/([^/]+/\.claude/worktrees/[^/]+)',
                3
            )
        ELSE {{ claude_folder(path) }}
    END
{%- endmacro %}
