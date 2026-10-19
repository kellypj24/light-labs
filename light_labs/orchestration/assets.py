"""Assets: raw.* landed from the lab's files, then every dbt node in analytics/.

Raw asset keys are the dbt source keys (["raw", <table>]), so dagster-dbt wires each
staging model to the asset that lands its source.
"""

import os

from dagster import AssetExecutionContext, AssetKey, AssetSpec, RetryPolicy, asset, multi_asset
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from light_labs import config

# dbt's profile reads DUCKDB_PATH; point it at the same file the ingest writes.
os.environ.setdefault("DUCKDB_PATH", str(config.VAR / "lab.duckdb"))

PROJECT = DbtProject(project_dir=config.REPO / "analytics")
PROJECT.prepare_if_dev()
DBT = DbtCliResource(project_dir=PROJECT, profiles_dir=str(PROJECT.project_dir))

# DuckDB has one writer. `just eval`, `just analytics` or a `lab` command can hold the
# file for a few seconds; retry rather than fail the run.
LOCKED = RetryPolicy(max_retries=3, delay=15)


@asset(
    key=AssetKey(["raw", "eval_samples"]),
    group_name="landing",
    retry_policy=LOCKED,
    description="Eval samples from var/evals/*.jsonl (`lab evals ingest`).",
)
def eval_samples(context: AssetExecutionContext) -> None:
    from light_labs.evals import results

    loaded = results.ingest()
    context.add_output_metadata({"runs": len(loaded), "rows": sum(loaded.values())})


@multi_asset(
    specs=[
        AssetSpec(
            AssetKey(["raw", "eval_run_log"]),
            description="Run records from var/evals/*.run.json.",
        ),
        AssetSpec(
            AssetKey(["raw", "eval_telemetry"]),
            description="Heat readings from var/evals/*.telemetry.jsonl.",
        ),
    ],
    group_name="landing",
    retry_policy=LOCKED,
)
def eval_run_health(context: AssetExecutionContext):
    from dagster import MaterializeResult

    from light_labs.evals import results

    runs, readings = results.ingest_health()
    yield MaterializeResult(asset_key=["raw", "eval_run_log"], metadata={"rows": runs})
    yield MaterializeResult(asset_key=["raw", "eval_telemetry"], metadata={"rows": readings})


@asset(
    key=AssetKey(["raw", "queue_items"]),
    group_name="landing",
    retry_policy=LOCKED,
    description="Robots' approval queues from var/<robot>/queue/ (`lab queue ingest`).",
)
def queue_items(context: AssetExecutionContext) -> None:
    from light_labs.core import queue_results

    loaded = queue_results.ingest(config.VAR)
    context.add_output_metadata({"robots": len(loaded), "rows": sum(loaded.values())})


@asset(
    key=AssetKey(["raw", "claude_records"]),
    group_name="landing",
    retry_policy=LOCKED,
    description="Claude Code transcripts from ~/.claude/projects (`lab claude ingest`).",
)
def claude_records(context: AssetExecutionContext) -> None:
    from light_labs.core import claude_results

    new, total = claude_results.ingest()
    context.add_output_metadata({"new": new, "rows": total})


class Translator(DagsterDbtTranslator):
    """dbt models grouped by layer: staging, intermediate, marts."""

    def get_group_name(self, dbt_resource_props):
        fqn = dbt_resource_props.get("fqn", [])
        return fqn[1] if len(fqn) > 2 else "analytics"


@dbt_assets(manifest=PROJECT.manifest_path, dagster_dbt_translator=Translator())
def analytics(context: AssetExecutionContext, dbt: DbtCliResource):
    """`dbt build` over the selected models: models, data tests and unit tests."""
    yield from dbt.cli(["build"], context=context).stream()


LANDING = [eval_samples, eval_run_health, queue_items, claude_records]
ALL_ASSETS = [*LANDING, analytics]
