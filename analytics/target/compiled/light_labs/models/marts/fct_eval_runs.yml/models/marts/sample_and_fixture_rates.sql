

WITH  __dbt__cte__stg_eval_samples as (

-- Fixture for stg_eval_samples
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('a' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(1 as INTEGER)
 as "sample_number",

    cast(True as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(False as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(False as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('a' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(2 as INTEGER)
 as "sample_number",

    cast(True as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(False as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(False as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('b' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(1 as INTEGER)
 as "sample_number",

    cast(True as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(False as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(True as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('b' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(2 as INTEGER)
 as "sample_number",

    cast(False as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(True as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(False as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
),  __dbt__cte__int_eval_fixtures_scored as (

-- Fixture for int_eval_fixtures_scored
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('a' as character varying)
 as "fixture", cast(null as character varying(256)) as "category", cast(null as character varying(256)) as "fixture_result_key", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count",

    cast(True as BOOLEAN)
 as "is_all_passed", cast(null as BOOLEAN) as "has_harness_error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('b' as character varying)
 as "fixture", cast(null as character varying(256)) as "category", cast(null as character varying(256)) as "fixture_result_key", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count",

    cast(False as BOOLEAN)
 as "is_all_passed", cast(null as BOOLEAN) as "has_harness_error"
), samples AS (

    SELECT * FROM __dbt__cte__stg_eval_samples

),

fixtures AS (

    SELECT
        run_id,
        contestant,
        COUNT(*) AS fixture_count,
        COUNT(*) FILTER (WHERE is_all_passed) AS passed_fixture_count
    FROM __dbt__cte__int_eval_fixtures_scored
    GROUP BY run_id, contestant

),

runs AS (

    SELECT
        run_id,
        contestant,
        ANY_VALUE(stage) AS stage,
        ANY_VALUE(role) AS role,
        ANY_VALUE(brain) AS brain,
        ANY_VALUE(git_commit) AS git_commit,
        BOOL_OR(is_dirty) AS is_dirty,
        ANY_VALUE(fixture_filter) AS fixture_filter,
        MIN(sampled_at) AS started_at,
        MAX(sampled_at) AS last_sample_at,
        MAX(sample_number) AS samples_per_fixture,
        COUNT(*) AS sample_count,
        COUNT(*) FILTER (WHERE is_passed) AS passed_sample_count,
        COUNT(*) FILTER (WHERE is_harness_error) AS harness_error_count,
        COUNT(*) FILTER (WHERE is_escalated) AS escalated_sample_count,
        AVG(latency_seconds) AS mean_latency_seconds,
        MEDIAN(latency_seconds) AS median_latency_seconds,
        SUM(cost_usd) AS total_cost_usd,
        BOOL_AND(COALESCE(is_isolated, TRUE)) AS is_isolated
    FROM samples
    GROUP BY run_id, contestant

)

SELECT
    runs.run_id || '|' || runs.contestant AS run_contestant_key,
    runs.run_id,
    runs.stage,
    runs.contestant,
    runs.role,
    runs.brain,
    runs.git_commit,
    runs.is_dirty,
    runs.fixture_filter,
    runs.fixture_filter IS NULL AS is_full_run,
    runs.started_at,
    runs.last_sample_at,
    runs.samples_per_fixture,
    runs.sample_count,
    runs.passed_sample_count,
    CASE
        WHEN runs.sample_count IS NULL OR runs.sample_count = 0
            THEN NULL
        ELSE runs.passed_sample_count::DOUBLE / runs.sample_count::DOUBLE
    END AS sample_pass_rate,
    fixtures.fixture_count,
    fixtures.passed_fixture_count,
    CASE
        WHEN fixtures.fixture_count IS NULL OR fixtures.fixture_count = 0
            THEN NULL
        ELSE fixtures.passed_fixture_count::DOUBLE / fixtures.fixture_count::DOUBLE
    END
        AS fixture_pass_rate,
    runs.escalated_sample_count,
    runs.harness_error_count,
    runs.mean_latency_seconds,
    runs.median_latency_seconds,
    runs.total_cost_usd,
    runs.is_isolated
FROM runs
INNER JOIN fixtures
    ON
        runs.run_id = fixtures.run_id
        AND runs.contestant = fixtures.contestant
