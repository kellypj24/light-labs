
    -- Build actual result given inputs
with dbt_internal_unit_test_actual as (
  select
    "stage","local_run_id","is_weapon_earned", 'actual' as "actual_or_expected"
  from (


WITH  __dbt__cte__fct_eval_runs as (

-- Fixture for fct_eval_runs
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s1-a' as character varying)
 as "run_id",

    cast('s1' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.92 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s1-b' as character varying)
 as "run_id",

    cast('s1' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('bass' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.95 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s2-a' as character varying)
 as "run_id",

    cast('s2' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.8 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s2-f' as character varying)
 as "run_id",

    cast('s2' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(False as BOOLEAN)
 as "is_full_run",

    cast('2026-10-02 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(1.0 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s2-b' as character varying)
 as "run_id",

    cast('s2' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('bass' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.85 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s3-a' as character varying)
 as "run_id",

    cast('s3' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.91 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s3-b' as character varying)
 as "run_id",

    cast('s3' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('bass' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(1.0 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s4-a' as character varying)
 as "run_id",

    cast('s4' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.99 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
), ranked AS (

    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY stage, role ORDER BY started_at DESC
        ) AS recency
    FROM __dbt__cte__fct_eval_runs
    WHERE is_full_run AND role IN ('megaman', 'bass')

),

local_runs AS (

    SELECT * FROM ranked
    WHERE role = 'megaman' AND recency = 1

),

cloud_runs AS (

    SELECT * FROM ranked
    WHERE role = 'bass' AND recency = 1

),

compared AS (

    SELECT
        local_runs.stage,
        local_runs.run_id AS local_run_id,
        local_runs.brain AS local_brain,
        local_runs.git_commit AS local_git_commit,
        local_runs.started_at AS local_started_at,
        local_runs.samples_per_fixture AS local_samples_per_fixture,
        local_runs.sample_pass_rate AS local_sample_pass_rate,
        local_runs.fixture_pass_rate AS local_fixture_pass_rate,
        local_runs.mean_latency_seconds AS local_mean_latency_seconds,
        cloud_runs.run_id AS cloud_run_id,
        cloud_runs.brain AS cloud_brain,
        cloud_runs.started_at AS cloud_started_at,
        cloud_runs.fixture_pass_rate AS cloud_fixture_pass_rate,
        cloud_runs.mean_latency_seconds AS cloud_mean_latency_seconds,
        cloud_runs.total_cost_usd AS cloud_cost_usd,
        cloud_runs.fixture_pass_rate - local_runs.fixture_pass_rate AS fixture_rate_gap
    FROM local_runs
    LEFT JOIN cloud_runs ON local_runs.stage = cloud_runs.stage

)

SELECT
    *,
    COALESCE(
        local_fixture_pass_rate >= 0.9
        AND fixture_rate_gap <= 0.05,
        FALSE
    ) AS is_weapon_earned
FROM compared
  ) _dbt_internal_unit_test_actual
),
-- Build expected result
dbt_internal_unit_test_expected as (
  select
    "stage", "local_run_id", "is_weapon_earned", 'expected' as "actual_or_expected"
  from (
    select

    cast('s1' as character varying)
 as "stage",

    cast('s1-a' as character varying)
 as "local_run_id",

    cast(True as BOOLEAN)
 as "is_weapon_earned"
union all
select

    cast('s2' as character varying)
 as "stage",

    cast('s2-a' as character varying)
 as "local_run_id",

    cast(False as BOOLEAN)
 as "is_weapon_earned"
union all
select

    cast('s3' as character varying)
 as "stage",

    cast('s3-a' as character varying)
 as "local_run_id",

    cast(False as BOOLEAN)
 as "is_weapon_earned"
union all
select

    cast('s4' as character varying)
 as "stage",

    cast('s4-a' as character varying)
 as "local_run_id",

    cast(False as BOOLEAN)
 as "is_weapon_earned"
  ) _dbt_internal_unit_test_expected
)
-- Union actual and expected results
select * from dbt_internal_unit_test_actual
union all
select * from dbt_internal_unit_test_expected
