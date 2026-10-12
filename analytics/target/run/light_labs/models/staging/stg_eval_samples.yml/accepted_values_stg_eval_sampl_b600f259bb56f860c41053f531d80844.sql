

    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (






with all_values as (

    select
        role as value_field,
        count(*) as n_records

    from "lab"."staging"."stg_eval_samples"
    group by role

)

select *
from all_values
where value_field not in (
    'megaman','proto','bass','mock'
)






    ) dbt_internal_test
