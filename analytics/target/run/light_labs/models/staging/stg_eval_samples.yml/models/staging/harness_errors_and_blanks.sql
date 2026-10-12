
    -- Build actual result given inputs
with dbt_internal_unit_test_actual as (
  select
    "sample_key","is_harness_error","is_escalated","fixture_filter", 'actual' as "actual_or_expected"
  from (


WITH  __dbt__cte__raw__eval_samples as (

-- Fixture for eval_samples
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "commit", cast(null as BOOLEAN) as "dirty",

    cast('' as character varying)
 as "filter",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "stage",

    cast('f1' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(1 as INTEGER)
 as "sample",

    cast(False as BOOLEAN)
 as "passed",

    cast('[{"name": "ran", "passed": false, "detail": "timeout"}]' as JSON)
 as "checks", cast(null as character varying(256)) as "draft",

    cast('' as character varying)
 as "escalate", cast(null as DOUBLE) as "latency_s", cast(null as DOUBLE) as "cost_usd", cast(null as BOOLEAN) as "isolated", cast(null as character varying(256)) as "error", cast(null as TIMESTAMP WITH TIME ZONE) as "at", cast(null as character varying(256)) as "source"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "commit", cast(null as BOOLEAN) as "dirty", cast(null as character varying(256)) as "filter",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "stage",

    cast('f1' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(2 as INTEGER)
 as "sample",

    cast(False as BOOLEAN)
 as "passed",

    cast('[{"name": "ran", "passed": true}, {"name": "escalate", "passed": false}]' as JSON)
 as "checks", cast(null as character varying(256)) as "draft",

    cast('do work' as character varying)
 as "escalate", cast(null as DOUBLE) as "latency_s", cast(null as DOUBLE) as "cost_usd", cast(null as BOOLEAN) as "isolated", cast(null as character varying(256)) as "error", cast(null as TIMESTAMP WITH TIME ZONE) as "at", cast(null as character varying(256)) as "source"
), source AS (

    SELECT *
    FROM __dbt__cte__raw__eval_samples

),

renamed AS (

    SELECT
        run_id,
        stage,
        contestant,
        role,
        brain,
        fixture,
        category,
        sample AS sample_number,
        passed AS is_passed,
        draft,
        latency_s AS latency_seconds,
        isolated AS is_isolated,
        "commit" AS git_commit,  -- noqa: RF06
        dirty AS is_dirty,
        checks,
        "at" AS sampled_at,  -- noqa: RF06
        source AS source_file,
        run_id || '|' || contestant || '|' || fixture || '|' || sample AS sample_key,
        -- The scorer's first check is `ran`; it fails alone when the runner
        -- or the model call broke, which is not the model's fault.
        COALESCE(
            checks -> '$[0]' ->> 'name' = 'ran'
            AND NOT CAST(checks -> '$[0]' ->> 'passed' AS BOOLEAN),
            FALSE
        ) AS is_harness_error,
        NULLIF(escalate, '') AS escalation,
        NULLIF(escalate, '') IS NOT NULL AS is_escalated,
        LENGTH(draft) AS draft_chars,
        COALESCE(cost_usd, 0) AS cost_usd,
        NULLIF("filter", '') AS fixture_filter,  -- noqa: RF06
        NULLIF(error, '') AS error
    FROM source

)

SELECT * FROM renamed
  ) _dbt_internal_unit_test_actual
),
-- Build expected result
dbt_internal_unit_test_expected as (
  select
    "sample_key", "is_harness_error", "is_escalated", "fixture_filter", 'expected' as "actual_or_expected"
  from (
    select

    cast('r1|megaman|f1|1' as character varying)
 as "sample_key",

    cast(True as BOOLEAN)
 as "is_harness_error",

    cast(False as BOOLEAN)
 as "is_escalated",

    cast(null as character varying(256))
 as "fixture_filter"
union all
select

    cast('r1|megaman|f1|2' as character varying)
 as "sample_key",

    cast(False as BOOLEAN)
 as "is_harness_error",

    cast(True as BOOLEAN)
 as "is_escalated",

    cast(null as character varying(256))
 as "fixture_filter"
  ) _dbt_internal_unit_test_expected
)
-- Union actual and expected results
select * from dbt_internal_unit_test_actual
union all
select * from dbt_internal_unit_test_expected
