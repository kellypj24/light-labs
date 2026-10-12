

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select check_key
from "lab"."intermediate"."int_eval_checks_unnested"
where check_key is null






    ) dbt_internal_test
