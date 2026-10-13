---
name: dagster-orchestration
description: How data flows into var/lab.duckdb through the lab's Dagster code location. Use when adding or changing an asset, job, sensor or schedule in light_labs/orchestration, wiring a new raw table or dbt model into the DAG, or debugging why a run did or did not happen.
audience: [auto]
---

`light_labs/orchestration/` is the only path data takes into `var/lab.duckdb`: `just
analytics` executes its `analytics_job`, and its sensors run narrower jobs. Distilled from
the data-engineering toolkit's `dagster-asset` skill and `orchestration/dagster`.

## The DAG

```
var/evals/*.jsonl ──────────▶ raw/eval_samples ─┐
var/evals/*.run.json ─┬─────▶ raw/eval_run_log  ├─▶ staging/* ─▶ intermediate/* ─▶ marts/*
var/evals/*.telemetry ┘      raw/eval_telemetry │      (one @dbt_assets: `dbt build`)
var/<robot>/queue/ ─────────▶ raw/queue_items ──┘
```

Asset keys mirror DuckDB tables: `raw/<table>` for landing, `<schema>/<model>` for dbt.
Landing assets call the same functions as the CLI (`results.ingest`,
`results.ingest_health`, `queue_results.ingest`); Dagster never has its own copy of the
logic. Don't add a second path (a script that loads raw.* or runs `dbt build` itself).

## Adding a raw table

1. Write the loader in the owning module (`light_labs/.../*_results.py`) with a CLI
   command and a test, as for the existing ones.
2. Declare it in `analytics/models/staging/_sources.yml` under source `raw`.
3. Add an `@asset` in `orchestration/assets.py` with `key=AssetKey(["raw", "<table>"])`,
   `group_name="landing"`, `retry_policy=LOCKED`, and append it to `LANDING`. The key
   must equal the dbt source key or the staging model hangs off nothing;
   `test_every_dbt_source_is_landed_by_an_asset` fails if you forget.
4. If a sensor should react to it, give its job a selection with `.downstream()`.

A new dbt model needs no orchestration change: `dbt parse` puts it in the manifest and
`@dbt_assets` picks it up. A new source does need step 3.

## Jobs and sensors

- A job selects landing assets plus `.downstream()`, so it rebuilds only what reads them.
- Every sensor or schedule that launches runs defaults to `STOPPED`; PJ turns it on in
  the UI. Schedules set `execution_timezone="UTC"`.
- Every sensor returns `SkipReason` while `live_fight()` finds a fight: one heavy job at
  a time on the laptop.
- Make requests idempotent: a cursor for "what I've already handled", and a `run_key`
  derived from it. Dagster drops a repeated `run_key`.
- On the first tick (no cursor), start from now. Don't replay history.
- Fights are never a Dagster job. They are heavy and PJ starts them. Dagster reacts to
  their files.

## DuckDB

One writer at a time. `ops/orchestration/dagster.yaml` caps the instance at one run. `LOCKED` retries a
landing asset that finds the file held by `just eval`, `just analytics` or `lab`.
`fight_finished` waits `SETTLE` after a fight ends so `just eval` can load first. Don't
raise `max_concurrent_runs`.

## Verify

```bash
just dagster-check  # dbt parse, definitions validate, tests/test_orchestration.py (incl. a full run over the fixtures)
just dagster        # UI on :3000; state in var/dagster
```

`tests/test_orchestration.py` pins: launching sensors start STOPPED, every dbt source has a
landing asset, every model is an asset, and sensors hold off during a fight. Add a case
there for any new sensor rule. Test sensor logic as plain functions over a temp `var/`
(see `finished_since`, `queue_fingerprint`); use `build_sensor_context` for the sensor
itself.

## Common mistakes

- A landing asset not appended to `LANDING` doesn't appear and raises no error.
- A raw key that doesn't match the dbt source key splits the graph in two.
- A stale manifest: `@dbt_assets` reads `analytics/target/manifest.json` at import.
  `just dagster` re-parses (dev mode); `just analytics` and `dagster-check` parse first.
- Reading `config.VAR` into a module constant in a sensor breaks the tests' patching.
  Read it inside the function.
