

  create view "lab"."intermediate"."int_eval_fixtures_scored__dbt_tmp" as (


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
FROM "lab"."staging"."stg_eval_samples"
GROUP BY run_id, stage, contestant, role, brain, fixture, category
  );
