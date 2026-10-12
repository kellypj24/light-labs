

SELECT
    run_id || '|' || contestant || '|' || check_name AS run_check_key,
    run_id,
    stage,
    contestant,
    role,
    check_name,
    COUNT(*) AS check_count,
    COUNT(*) FILTER (WHERE NOT is_passed) AS failed_count,
    CASE
        WHEN COUNT(*) IS NULL OR COUNT(*) = 0
            THEN NULL
        ELSE COUNT(*) FILTER (WHERE NOT is_passed)::DOUBLE / COUNT(*)::DOUBLE
    END AS failure_rate,
    COUNT(DISTINCT fixture) FILTER (WHERE NOT is_passed) AS failed_fixture_count
FROM "lab"."intermediate"."int_eval_checks_unnested"
GROUP BY run_id, stage, contestant, role, check_name
