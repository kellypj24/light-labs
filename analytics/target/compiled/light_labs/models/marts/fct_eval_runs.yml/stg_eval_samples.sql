
-- Fixture for stg_eval_samples
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('a' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(1 as INTEGER)
 as "sample_number",

    cast(True as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(False as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(False as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('a' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(2 as INTEGER)
 as "sample_number",

    cast(True as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(False as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(False as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('b' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(1 as INTEGER)
 as "sample_number",

    cast(True as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(False as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(True as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
union all
select

    cast('r1' as character varying)
 as "run_id", cast(null as character varying(256)) as "stage",

    cast('megaman' as character varying)
 as "contestant", cast(null as character varying(256)) as "role", cast(null as character varying(256)) as "brain",

    cast('b' as character varying)
 as "fixture", cast(null as character varying(256)) as "category",

    cast(2 as INTEGER)
 as "sample_number",

    cast(False as BOOLEAN)
 as "is_passed", cast(null as character varying(256)) as "draft", cast(null as DOUBLE) as "latency_seconds", cast(null as BOOLEAN) as "is_isolated", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as JSON) as "checks", cast(null as TIMESTAMP WITH TIME ZONE) as "sampled_at", cast(null as character varying(256)) as "source_file", cast(null as character varying(256)) as "sample_key",

    cast(True as BOOLEAN)
 as "is_harness_error", cast(null as character varying(256)) as "escalation",

    cast(False as BOOLEAN)
 as "is_escalated", cast(null as BIGINT) as "draft_chars", cast(null as DOUBLE) as "cost_usd", cast(null as character varying(256)) as "fixture_filter", cast(null as character varying(256)) as "error"
