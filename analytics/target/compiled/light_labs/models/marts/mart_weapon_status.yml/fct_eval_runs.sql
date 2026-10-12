
-- Fixture for fct_eval_runs
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s1-a' as character varying)
 as "run_id",

    cast('s1' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.92 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s1-b' as character varying)
 as "run_id",

    cast('s1' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('bass' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.95 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s2-a' as character varying)
 as "run_id",

    cast('s2' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.8 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s2-f' as character varying)
 as "run_id",

    cast('s2' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(False as BOOLEAN)
 as "is_full_run",

    cast('2026-10-02 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(1.0 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s2-b' as character varying)
 as "run_id",

    cast('s2' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('bass' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.85 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s3-a' as character varying)
 as "run_id",

    cast('s3' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.91 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s3-b' as character varying)
 as "run_id",

    cast('s3' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('bass' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(1.0 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
union all
select cast(null as character varying(256)) as "run_contestant_key",

    cast('s4-a' as character varying)
 as "run_id",

    cast('s4' as character varying)
 as "stage", cast(null as character varying(256)) as "contestant",

    cast('megaman' as character varying)
 as "role", cast(null as character varying(256)) as "brain", cast(null as character varying(256)) as "git_commit", cast(null as BOOLEAN) as "is_dirty", cast(null as character varying(256)) as "fixture_filter",

    cast(True as BOOLEAN)
 as "is_full_run",

    cast('2026-10-01 00:00:00' as TIMESTAMP WITH TIME ZONE)
 as "started_at", cast(null as TIMESTAMP WITH TIME ZONE) as "last_sample_at", cast(null as INTEGER) as "samples_per_fixture", cast(null as BIGINT) as "sample_count", cast(null as BIGINT) as "passed_sample_count", cast(null as DOUBLE) as "sample_pass_rate", cast(null as BIGINT) as "fixture_count", cast(null as BIGINT) as "passed_fixture_count",

    cast(0.99 as DOUBLE)
 as "fixture_pass_rate", cast(null as BIGINT) as "escalated_sample_count", cast(null as BIGINT) as "harness_error_count", cast(null as DOUBLE) as "mean_latency_seconds", cast(null as DOUBLE) as "median_latency_seconds", cast(null as DOUBLE) as "total_cost_usd", cast(null as BOOLEAN) as "is_isolated"
