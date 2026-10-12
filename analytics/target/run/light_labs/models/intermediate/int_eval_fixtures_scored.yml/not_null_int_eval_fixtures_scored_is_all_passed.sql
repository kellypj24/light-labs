

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select is_all_passed
from "lab"."intermediate"."int_eval_fixtures_scored"
where is_all_passed is null






    ) dbt_internal_test
