

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select fixture_result_key
from "lab"."intermediate"."int_eval_fixtures_scored"
where fixture_result_key is null






    ) dbt_internal_test
