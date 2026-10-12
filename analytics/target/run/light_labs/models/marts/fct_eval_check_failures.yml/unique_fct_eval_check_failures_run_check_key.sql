

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (






select
    run_check_key as unique_field,
    count(*) as n_records

from "lab"."marts"."fct_eval_check_failures"
where run_check_key is not null
group by run_check_key
having count(*) > 1






    ) dbt_internal_test
