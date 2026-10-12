{#
    One row per stage: has the local generalist earned the stage's weapon?
    Compares Mega Man's latest full run with Bass's latest full run. Earned when
    Mega Man's fixture pass rate clears `weapon_min_fixture_rate` and trails Bass
    by no more than `weapon_max_gap`. No Bass run, no weapon: the ceiling must
    be measured, not assumed.
#}

WITH ranked AS (

    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY stage, role ORDER BY started_at DESC
        ) AS recency
    FROM {{ ref('fct_eval_runs') }}
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
        local_fixture_pass_rate >= {{ var('weapon_min_fixture_rate') }}
        AND fixture_rate_gap <= {{ var('weapon_max_gap') }},
        FALSE
    ) AS is_weapon_earned
FROM compared
