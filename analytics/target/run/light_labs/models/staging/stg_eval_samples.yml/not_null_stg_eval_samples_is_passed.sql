

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select is_passed
from "lab"."staging"."stg_eval_samples"
where is_passed is null






    ) dbt_internal_test
