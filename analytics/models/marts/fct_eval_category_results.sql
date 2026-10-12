{# One row per category per contestant per run. #}

SELECT
    run_id || '|' || contestant || '|' || category AS run_category_key,
    run_id,
    stage,
    contestant,
    role,
    category,
    SUM(sample_count) AS sample_count,
    SUM(passed_sample_count) AS passed_sample_count,
    {{ safe_divide('SUM(passed_sample_count)', 'SUM(sample_count)') }} AS sample_pass_rate,
    COUNT(*) AS fixture_count,
    COUNT(*) FILTER (WHERE is_all_passed) AS passed_fixture_count,
    {{ safe_divide('COUNT(*) FILTER (WHERE is_all_passed)', 'COUNT(*)') }} AS fixture_pass_rate
FROM {{ ref('int_eval_fixtures_scored') }}
GROUP BY run_id, stage, contestant, role, category
