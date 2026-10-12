


    create  table
      "lab"."marts"."fct_eval_category_results__dbt_tmp"


    as (


SELECT
    run_id || '|' || contestant || '|' || category AS run_category_key,
    run_id,
    stage,
    contestant,
    role,
    category,
    SUM(sample_count) AS sample_count,
    SUM(passed_sample_count) AS passed_sample_count,
    CASE
        WHEN SUM(sample_count) IS NULL OR SUM(sample_count) = 0
            THEN NULL
        ELSE SUM(passed_sample_count)::DOUBLE / SUM(sample_count)::DOUBLE
    END AS sample_pass_rate,
    COUNT(*) AS fixture_count,
    COUNT(*) FILTER (WHERE is_all_passed) AS passed_fixture_count,
    CASE
        WHEN COUNT(*) IS NULL OR COUNT(*) = 0
            THEN NULL
        ELSE COUNT(*) FILTER (WHERE is_all_passed)::DOUBLE / COUNT(*)::DOUBLE
    END AS fixture_pass_rate
FROM "lab"."intermediate"."int_eval_fixtures_scored"
GROUP BY run_id, stage, contestant, role, category
    );
