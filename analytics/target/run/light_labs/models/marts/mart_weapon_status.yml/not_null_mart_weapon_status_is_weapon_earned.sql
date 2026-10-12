

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (








select is_weapon_earned
from "lab"."marts"."mart_weapon_status"
where is_weapon_earned is null






    ) dbt_internal_test
