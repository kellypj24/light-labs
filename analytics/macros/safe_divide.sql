{% macro safe_divide(numerator, denominator) -%}
    {#- NULL instead of an error when the denominator is zero or NULL. -#}
    CASE
        WHEN {{ denominator }} IS NULL OR {{ denominator }} = 0
            THEN NULL
        ELSE {{ numerator }}::DOUBLE / {{ denominator }}::DOUBLE
    END
{%- endmacro %}
