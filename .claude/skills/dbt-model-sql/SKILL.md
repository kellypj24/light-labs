---
name: dbt-model-sql
description: How a robot writes one dbt model's SQL for the lab's DuckDB project. Distilled from the data-engineering toolkit's dbt-model skill.
audience: [robots]
load: always
---

You write one dbt model: a single SELECT over upstream models, run on DuckDB.

Output: only the SQL of the model file. No markdown fences, no explanation, no final
semicolon (dbt wraps the model, so a semicolon is a syntax error).

Read upstream models with `{{ ref('model_name') }}` only. Never write schema names such as
`staging.x` or `marts.x`. Use only the columns listed for each upstream model.

Before writing, name the grain: what one output row is. GROUP BY exactly those columns.

Questions about "every" or "share of X where all Y" need two steps: aggregate to the
inner grain in one CTE (for example one row per fixture, with BOOL_AND(is_passed)), then
aggregate that CTE to the output grain. One GROUP BY over raw rows gets these wrong.

Return exactly the requested columns, with exactly the requested names. Give every derived
column an alias with AS.

Patterns:
- conditional counts: COUNT(*) FILTER (WHERE condition)
- all / any: BOOL_AND(x) / BOOL_OR(x)
- rates: {{ safe_divide('numerator', 'denominator') }}
- latest or best per group: ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ... DESC) in a
  CTE, then keep row 1
- previous value: LAG(x) OVER (PARTITION BY ... ORDER BY ...)
- JSON lists: UNNEST(FROM_JSON(col, '[{"name": "VARCHAR", "passed": "BOOLEAN"}]'))
- keep groups that have no matching rows: COUNT(*) FILTER (...) instead of WHERE

Style: CTEs for each step, keywords UPPER, identifiers lower, no trailing comma before FROM.
