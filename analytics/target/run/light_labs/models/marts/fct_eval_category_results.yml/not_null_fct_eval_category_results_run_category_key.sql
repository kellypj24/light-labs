

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select run_category_key
from "lab"."marts"."fct_eval_category_results"
where run_category_key is null






    ) dbt_internal_test
