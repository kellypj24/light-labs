{% macro claude_folder(path) -%}
    {#-
        The top-level folder under the home directory a path is in: a project, or one of
        the buckets `home`, `claude-config` (~/.claude), `scratch` (temp dirs) and
        `other`. ~ and $HOME count as the home directory; a relative path, or a folder
        named by a shell variable, is NULL.
    -#}
    {%- set path = "(" ~ path ~ ")" %}
    CASE
        WHEN {{ path }} IS NULL OR {{ path }} = '' THEN NULL
        WHEN REGEXP_MATCHES({{ path }}, '^(/private)?/(tmp|var/folders)/') THEN 'scratch'
        WHEN REGEXP_MATCHES({{ path }}, '^(/(Users|home)/[^/]+|~|\$HOME)/?$') THEN 'home'
        WHEN REGEXP_MATCHES({{ path }}, '^(/(Users|home)/[^/]+|~|\$HOME)/\.claude(/|$)')
            THEN 'claude-config'
        WHEN REGEXP_MATCHES({{ path }}, '^(/(Users|home)/[^/]+|~|\$HOME)/Library(/|$)')
            THEN 'home'
        -- A shell variable (`~/$repo` in a loop): unknown.
        WHEN REGEXP_MATCHES({{ path }}, '^(/(Users|home)/[^/]+|~|\$HOME)/\$') THEN NULL
        WHEN REGEXP_MATCHES({{ path }}, '^(/(Users|home)/[^/]+|~|\$HOME)/')
            THEN REGEXP_EXTRACT({{ path }}, '^(/(Users|home)/[^/]+|~|\$HOME)/([^/]+)', 3)
        WHEN STARTS_WITH({{ path }}, '/') THEN 'other'
    END
{%- endmacro %}
