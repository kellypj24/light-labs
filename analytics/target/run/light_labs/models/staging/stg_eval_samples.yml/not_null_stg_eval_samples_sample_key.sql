

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select sample_key
from "lab"."staging"."stg_eval_samples"
where sample_key is null






    ) dbt_internal_test
