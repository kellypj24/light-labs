{% macro claude_shell_task(part, writes_files) -%}
    {#-
        `rank|task` for one part of a shell command (split at &&, ;, | and newlines,
        setup stripped). A command counts as its highest-ranked part: the wait in
        `cd x && sleep 30 && gh pr checks`, the curl in `rm -f out; curl ...`.
        `writes_files` says the whole command writes files (a Python heredoc's body).
    -#}
    CASE
        WHEN REGEXP_MATCHES({{ part }}, '^(until|sleep|wait)\b') THEN '9|wait'
        WHEN
            REGEXP_MATCHES(
                {{ part }},
                '^(just\s+\S*check|just\s+(test|hooks)|pytest|ruff|sqlfluff|dbt|pre-commit'
                || '|go\s+(test|vet)|npm\s+test|tsc|dotnet\s+(build|test)'
                || '|claude\s+plugin\s+(validate|test))\b'
            )
            OR REGEXP_MATCHES(
                {{ part }}, '^(uvx|npx)\s+(-\S+\s+)*\S*(ruff|pre-commit|sqlfluff|tsc)'
            )
            OR REGEXP_MATCHES({{ part }}, '^(uv\s+run\s+(--\S+\s+)*)?lab\s+git\s+ship\b')
            THEN '8|checks'
        WHEN REGEXP_MATCHES({{ part }}, '^gh\b') THEN '7|github'
        WHEN
            REGEXP_MATCHES({{ part }}, '^(uv\s+run\s+(--\S+\s+)*)?lab\s+git\b')
            OR REGEXP_MATCHES({{ part }}, '^git\b')
            THEN '6|git'
        WHEN REGEXP_MATCHES({{ part }}, '^(curl|wget|ssh|scp|nc|ping)\b') THEN '5|network'
        WHEN
            REGEXP_MATCHES(
                {{ part }},
                '^(launchctl|docker|brew|pkill|kill|ps|lsof|pgrep|tailscale|security|open)\b'
            )
            THEN '4|services'
        WHEN REGEXP_MATCHES({{ part }}, '^(sed|perl)\s+(-\w*i|--in-place)') THEN '3|edit'
        WHEN REGEXP_MATCHES({{ part }}, '^python3?\b') AND {{ writes_files }} THEN '3|edit'
        WHEN
            REGEXP_MATCHES({{ part }}, '^(cat|tee|printf|echo)\b.*>{1,2}\s*[^&\s]')
            AND NOT REGEXP_MATCHES({{ part }}, '>\s*/dev/null')
            THEN '3|edit'
        WHEN
            REGEXP_MATCHES(
                {{ part }}, '^(python3?|uv|uvx|node|go|just|lab|npm|npx|bash|sh|make|dotnet)\b'
            )
            THEN '2|run'
        WHEN REGEXP_MATCHES({{ part }}, '^(mkdir|cp|mv|rm|touch|chmod|ln|tee)\b') THEN '1|files'
        WHEN
            REGEXP_MATCHES(
                {{ part }},
                '^(cat|head|tail|less|sed|awk|grep|rg|find|ls|wc|diff|file|stat|tree|jq|du)\b'
            )
            THEN '1|read'
        ELSE '0|other'
    END
{%- endmacro %}
