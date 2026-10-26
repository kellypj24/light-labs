{#
    One row per stage: has a local brain earned the stage's weapon?
    Takes each local brain's latest full run (Mega Man or a Proto challenger), keeps
    the best by fixture pass rate (Mega Man on a tie), and compares it with Bass's
    latest full run. Earned when that rate clears the stage's floor and trails Bass
    by no more than its gap. Routing is per stage, so a Proto brain can win one stage
    for its robot. The bar is the one recorded on the local run (the stage YAML's
    `bar:` at the time), else the `weapon_*` vars. No Bass run, no weapon: the
    ceiling must be measured, not assumed.
#}

WITH full_runs AS (

    SELECT * FROM {{ ref('fct_eval_runs') }}
    WHERE is_full_run AND role IN ('mega-man', 'proto', 'bass')

),

latest_local AS (

    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY stage, brain ORDER BY started_at DESC
        ) AS recency
    FROM full_runs
    WHERE role IN ('mega-man', 'proto')

),

local_runs AS (

    SELECT * FROM latest_local
    WHERE recency = 1
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY stage
        ORDER BY fixture_pass_rate DESC, role = 'mega-man' DESC, started_at DESC
    ) = 1

),

cloud_runs AS (

    SELECT * FROM full_runs
    WHERE role = 'bass'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY stage ORDER BY started_at DESC) = 1

),

compared AS (

    SELECT
        local_runs.stage,
        local_runs.run_id AS local_run_id,
        local_runs.role AS local_role,
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
        cloud_runs.fixture_pass_rate - local_runs.fixture_pass_rate AS fixture_rate_gap,
        COALESCE(
            local_runs.bar_min_fixture_rate, {{ var('weapon_min_fixture_rate') }}
        ) AS bar_min_fixture_rate,
        COALESCE(local_runs.bar_max_gap, {{ var('weapon_max_gap') }}) AS bar_max_gap
    FROM local_runs
    LEFT JOIN cloud_runs ON local_runs.stage = cloud_runs.stage

)

SELECT
    *,
    COALESCE(
        local_fixture_pass_rate >= bar_min_fixture_rate
        AND fixture_rate_gap <= bar_max_gap,
        FALSE
    ) AS is_weapon_earned
FROM compared
