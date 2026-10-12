{#
    One row per check name per contestant per run: which assertions a model
    trips, the starting point for prompt and skill changes.
#}

SELECT
    run_id || '|' || contestant || '|' || check_name AS run_check_key,
    run_id,
    stage,
    contestant,
    role,
    check_name,
    COUNT(*) AS check_count,
    COUNT(*) FILTER (WHERE NOT is_passed) AS failed_count,
    {{ safe_divide('COUNT(*) FILTER (WHERE NOT is_passed)', 'COUNT(*)') }} AS failure_rate,
    COUNT(DISTINCT fixture) FILTER (WHERE NOT is_passed) AS failed_fixture_count
FROM {{ ref('int_eval_checks_unnested') }}
GROUP BY run_id, stage, contestant, role, check_name
