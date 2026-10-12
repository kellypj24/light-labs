



select
    sample_key as unique_field,
    count(*) as n_records

from "lab"."staging"."stg_eval_samples"
where sample_key is not null
group by sample_key
having count(*) > 1
