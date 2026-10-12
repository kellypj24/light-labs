{#
    One row per contestant per run: the headline numbers the runner prints, plus
    which code produced them. sample_pass_rate counts samples; fixture_pass_rate
    counts fixtures whose every sample passed.
#}

WITH samples AS (

    SELECT * FROM {{ ref('stg_eval_samples') }}

),

fixtures AS (

    SELECT
        run_id,
        contestant,
        COUNT(*) AS fixture_count,
        COUNT(*) FILTER (WHERE is_all_passed) AS passed_fixture_count
    FROM {{ ref('int_eval_fixtures_scored') }}
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
        ANY_VALUE(bar_min_fixture_rate) AS bar_min_fixture_rate,
        ANY_VALUE(bar_max_gap) AS bar_max_gap,
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
    runs.bar_min_fixture_rate,
    runs.bar_max_gap,
    runs.started_at,
    runs.last_sample_at,
    runs.samples_per_fixture,
    runs.sample_count,
    runs.passed_sample_count,
    {{ safe_divide('runs.passed_sample_count', 'runs.sample_count') }} AS sample_pass_rate,
    fixtures.fixture_count,
    fixtures.passed_fixture_count,
    {{ safe_divide('fixtures.passed_fixture_count', 'fixtures.fixture_count') }}
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
