



with child as (
    select sample_key as from_field
    from "lab"."intermediate"."int_eval_checks_unnested"
    where sample_key is not null
),

parent as (
    select sample_key as to_field
    from "lab"."staging"."stg_eval_samples"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null
