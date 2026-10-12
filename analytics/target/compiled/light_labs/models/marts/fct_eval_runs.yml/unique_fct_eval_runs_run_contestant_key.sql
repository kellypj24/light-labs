



select
    run_contestant_key as unique_field,
    count(*) as n_records

from "lab"."marts"."fct_eval_runs"
where run_contestant_key is not null
group by run_contestant_key
having count(*) > 1
