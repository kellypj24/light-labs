
-- Fixture for int_eval_fixtures_scored
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('a' as character varying)
 as "fixture", cast(null as character varying(256)) as "category", cast(null as character varying(256)) as "fixture_result_key", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count",

    cast(True as BOOLEAN)
 as "is_all_passed", cast(null as BOOLEAN) as "has_harness_error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('b' as character varying)
 as "fixture", cast(null as character varying(256)) as "category", cast(null as character varying(256)) as "fixture_result_key", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count",

    cast(False as BOOLEAN)
 as "is_all_passed", cast(null as BOOLEAN) as "has_harness_error"
