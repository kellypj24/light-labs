

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select fixture
from "lab"."raw"."eval_samples"
where fixture is null






    ) dbt_internal_test
