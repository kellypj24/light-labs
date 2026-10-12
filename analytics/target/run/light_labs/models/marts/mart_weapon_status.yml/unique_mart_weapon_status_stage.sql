

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (






select
    stage as unique_field,
    count(*) as n_records

from "lab"."marts"."mart_weapon_status"
where stage is not null
group by stage
having count(*) > 1






    ) dbt_internal_test
