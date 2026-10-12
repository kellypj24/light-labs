

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select run_id
from "lab"."staging"."stg_eval_samples"
where run_id is null






    ) dbt_internal_test
