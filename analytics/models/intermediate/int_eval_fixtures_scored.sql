{#
    One row per fixture per contestant per run. A fixture passes only when every
    one of its samples passed: the bar a weapon is judged on.
#}

SELECT
    run_id,
    stage,
    contestant,
    role,
    brain,
    fixture,
    category,
    run_id || '|' || contestant || '|' || fixture AS fixture_result_key,
    COUNT(*) AS sample_count,
    COUNT(*) FILTER (WHERE is_passed) AS passed_sample_count,
    BOOL_AND(is_passed) AS is_all_passed,
    BOOL_OR(is_harness_error) AS has_harness_error
FROM {{ ref('stg_eval_samples') }}
GROUP BY run_id, stage, contestant, role, brain, fixture, category
