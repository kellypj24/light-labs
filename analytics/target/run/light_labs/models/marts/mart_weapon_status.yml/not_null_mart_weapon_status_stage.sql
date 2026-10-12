

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select stage
from "lab"."marts"."mart_weapon_status"
where stage is null






    ) dbt_internal_test
