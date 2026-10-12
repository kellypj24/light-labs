

  create view "lab"."intermediate"."int_eval_checks_unnested__dbt_tmp" as (


WITH samples AS (

    SELECT
        sample_key,
        run_id,
        stage,
        contestant,
        role,
        fixture,
        category,
        FROM_JSON(
            checks, '[{"name": "VARCHAR", "passed": "BOOLEAN", "detail": "VARCHAR"}]'
        ) AS check_list
    FROM "lab"."staging"."stg_eval_samples"

),

unnested AS (

    SELECT
        sample_key,
        run_id,
        stage,
        contestant,
        role,
        fixture,
        category,
        UNNEST(check_list) AS check_result,
        GENERATE_SUBSCRIPTS(check_list, 1) AS check_index
    FROM samples

)

SELECT
    unnested.sample_key,
    unnested.run_id,
    unnested.stage,
    unnested.contestant,
    unnested.role,
    unnested.fixture,
    unnested.category,
    unnested.check_index,
    check_result.name AS check_name,
    unnested.sample_key || '|' || unnested.check_index AS check_key,
    COALESCE(check_result.passed, FALSE) AS is_passed,
    NULLIF(check_result.detail, '') AS check_detail
FROM unnested
  );
