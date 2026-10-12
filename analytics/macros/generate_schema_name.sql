{% macro generate_schema_name(custom_schema_name, node) -%}
    {#-
        One environment: a layer's schema is its name (staging, intermediate, marts),
        beside the `raw` schema that `lab evals ingest` writes.
    -#}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
