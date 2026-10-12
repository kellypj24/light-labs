



select
    fixture_result_key as unique_field,
    count(*) as n_records

from "lab"."intermediate"."int_eval_fixtures_scored"
where fixture_result_key is not null
group by fixture_result_key
having count(*) > 1
