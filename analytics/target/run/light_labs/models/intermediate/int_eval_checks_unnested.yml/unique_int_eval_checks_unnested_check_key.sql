

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (






select
    check_key as unique_field,
    count(*) as n_records

from "lab"."intermediate"."int_eval_checks_unnested"
where check_key is not null
group by check_key
having count(*) > 1






    ) dbt_internal_test
