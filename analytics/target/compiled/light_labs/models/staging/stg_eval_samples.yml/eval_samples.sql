
-- Fixture for eval_samples
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "commit", cast(null as BOOLEAN) as "dirty",

    cast('' as character varying)
 as "filter",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "stage",

    cast('f1' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(1 as INTEGER)
 as "sample",

    cast(False as BOOLEAN)
 as "passed",

    cast('[{"name": "ran", "passed": false, "detail": "timeout"}]' as JSON)
 as "checks", cast(null as character varying(256)) as "draft",

    cast('' as character varying)
 as "escalate", cast(null as DOUBLE) as "latency_s", cast(null as DOUBLE) as "cost_usd", cast(null as BOOLEAN) as "isolated", cast(null as character varying(256)) as "error", cast(null as TIMESTAMP WITH TIME ZONE) as "at", cast(null as character varying(256)) as "source"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "commit", cast(null as BOOLEAN) as "dirty", cast(null as character varying(256)) as "filter",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "stage",

    cast('f1' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(2 as INTEGER)
 as "sample",

    cast(False as BOOLEAN)
 as "passed",

    cast('[{"name": "ran", "passed": true}, {"name": "escalate", "passed": false}]' as JSON)
 as "checks", cast(null as character varying(256)) as "draft",

    cast('do work' as character varying)
 as "escalate", cast(null as DOUBLE) as "latency_s", cast(null as DOUBLE) as "cost_usd", cast(null as BOOLEAN) as "isolated", cast(null as character varying(256)) as "error", cast(null as TIMESTAMP WITH TIME ZONE) as "at", cast(null as character varying(256)) as "source"
