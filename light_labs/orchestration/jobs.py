"""Jobs. Each lands raw data and rebuilds only the dbt nodes downstream of it."""

from dagster import AssetSelection, define_asset_job

from light_labs.orchestration.assets import (
    calibration,
    claude_records,
    eval_run_health,
    eval_samples,
    health_workouts,
    queue_items,
    strong_sets,
)

evals_job = define_asset_job(
    "evals_job",
    selection=AssetSelection.assets(eval_samples, eval_run_health).downstream(),
    description="Land eval samples and run health, then build what reads them.",
)
queue_job = define_asset_job(
    "queue_job",
    selection=AssetSelection.assets(queue_items, calibration).downstream(),
    description="Land the approval queues and refit calibration (Roll's Dependabot answers "
    "are pairs), then build what reads them.",
)
claude_job = define_asset_job(
    "claude_job",
    selection=AssetSelection.assets(claude_records).downstream(),
    description="Land Claude Code's transcripts, then build what reads them.",
)
strong_job = define_asset_job(
    "strong_job",
    selection=AssetSelection.assets(strong_sets).downstream(),
    description="Land the newest Strong export, then build what reads it.",
)
health_job = define_asset_job(
    "health_job",
    selection=AssetSelection.assets(health_workouts).downstream(),
    description="Upsert the Health workouts drops, then build what reads them.",
)
analytics_job = define_asset_job(
    "analytics_job",
    selection=AssetSelection.all(),
    description="Everything; what `just analytics` runs.",
)

ALL_JOBS = [evals_job, queue_job, claude_job, strong_job, health_job, analytics_job]
