



select
    run_category_key as unique_field,
    count(*) as n_records

from "lab"."marts"."fct_eval_category_results"
where run_category_key is not null
group by run_category_key
having count(*) > 1
