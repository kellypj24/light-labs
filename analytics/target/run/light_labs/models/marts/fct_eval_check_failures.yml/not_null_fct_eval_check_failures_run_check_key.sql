

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select run_check_key
from "lab"."marts"."fct_eval_check_failures"
where run_check_key is null






    ) dbt_internal_test
