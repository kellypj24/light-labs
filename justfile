# Same checks as CI. Run `just check` before pushing.

# profiles.yml lives in analytics/, not ~/.dbt
export DBT_PROFILES_DIR := justfile_directory() / "analytics"

default: check

# Pre-commit hooks (hygiene, ruff, zizmor, gitleaks) + unit tests, as a heavy job
# (`lab heavy`: refuses a busy machine, holds ~/.cache/light-labs/heavy.lock; a no-op in CI)
check:
    uv run --locked lab heavy run check -- just _check

_check: hooks test evals-check analytics-check dagster-check

# Every pre-commit hook over every file, untracked ones included (--all-files skips them)
hooks:
    git ls-files -z --cached --others --exclude-standard | xargs -0 uvx pre-commit@4.6.2 run --show-diff-on-failure --files

test:
    uv run --locked python -m unittest discover -s tests -t .

# Install the hooks so they run on every local commit
install-hooks:
    uvx pre-commit@4.6.2 install

# Auto-fix what ruff can, then format
fix:
    uvx ruff@0.17.0 check --fix .
    uvx ruff@0.17.0 format .

# Eval harness: format, vet, unit tests, and a smoke run against the mock contestant
evals-check:
    test -z "$(gofmt -l evals)" || (gofmt -l evals && exit 1)
    go -C evals vet ./...
    go -C evals test ./...
    go -C evals run . -contestants mock -samples 1 -out "$(mktemp -d)" > /dev/null
    # dbt-model's mock answers with each reference: every reference must build and match
    go -C evals run . -stage dbt-model -contestants mock -samples 1 -min-pass 1 -out "$(mktemp -d)" > /dev/null
    # commit-message's mock answers with each reference: every reference must pass every check
    go -C evals run . -stage commit-message -contestants mock -samples 1 -min-pass 1 -out "$(mktemp -d)" > /dev/null
    # mail-keep wiring: every fixture loads and runs (the mock answers no class: keep/unsure)
    go -C evals run . -stage mail-keep -contestants mock -samples 1 -out "$(mktemp -d)" > /dev/null

# Boss fight with real models. Runs locally only; one at a time on a laptop.
# Results land in var/evals/*.jsonl and are loaded into var/lab.duckdb.
# just eval reply-draft mega-man,bass 3
eval stage="reply-draft" contestants="mega-man" samples="3" *args="":
    status=0; uv run --locked lab heavy run fight -- go -C evals run . -stage {{stage}} -contestants {{contestants}} -samples {{samples}} {{args}} || status=$?; just analytics > /dev/null; exit $status

# Follow fights live from a second terminal: the latest, then each next one (Ctrl-C quits).
# With a run_id, that run only.
watch run_id="":
    uv run --locked lab evals watch {{run_id}}

# Recent eval runs from marts.fct_eval_runs
runs *args="":
    uv run --locked lab evals runs {{args}}

# Approval queues: can a robot's draft kind skip approval yet?
queue *args="":
    uv run --locked lab queue status {{args}}

# Load var/evals and the robots' queues into var/lab.duckdb, then build the dbt project:
# Dagster's analytics_job, recorded in var/dagster beside the sensors' runs
analytics: _dagster-home
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    DAGSTER_HOME="$PWD/var/dagster" uv run --locked --group orchestration dagster job execute -m light_labs.orchestration -j analytics_job

# dbt lint and build on the synthetic fixtures in a throwaway database (same as CI)
analytics-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    LAB_VAR="$tmp" uv run --locked lab evals ingest analytics/fixtures/*.jsonl
    LAB_VAR="$tmp" uv run --locked lab queue ingest --root analytics/fixtures/queue
    LAB_VAR="$tmp" uv run --locked lab claude ingest --projects analytics/fixtures/claude/projects
    cd analytics
    uv run --locked --group analytics sqlfluff lint models macros
    DUCKDB_PATH="$tmp/lab.duckdb" uv run --locked --group analytics dbt build --quiet
    cd ..
    uv run --locked --group analytics python -m unittest tests.test_dbt_model tests.test_autosend tests.test_commit_message
    LAB_VAR="$tmp" uv run --locked lab evals runs

# Dagster UI (http://127.0.0.1:3000). The sensors run in the daemon, not here.
dagster: _dagster-home
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    DAGSTER_HOME="$PWD/var/dagster" uv run --locked --group orchestration dagster-webserver -m light_labs.orchestration -p 3000

# The daemon that ticks the sensors; launchd runs this (ops/com.pjkelly.light-labs.dagster.plist)
dagster-daemon: _dagster-home
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    DAGSTER_HOME="$PWD/var/dagster" exec uv run --locked --group orchestration dagster-daemon run -m light_labs.orchestration

# Install (or reinstall) Rush's heartbeat and phone page as launchd jobs
rush-install:
    #!/usr/bin/env bash
    set -euo pipefail
    for job in rush rush-remote; do
        plist=~/Library/LaunchAgents/com.pjkelly.light-labs.$job.plist
        launchctl bootout gui/$(id -u)/com.pjkelly.light-labs.$job 2>/dev/null || true
        cp ops/com.pjkelly.light-labs.$job.plist "$plist"
        launchctl bootstrap gui/$(id -u) "$plist"
    done

# Install and start the daemon's launchd job
dagster-install: _dagster-home
    cp ops/com.pjkelly.light-labs.dagster.plist ~/Library/LaunchAgents/
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pjkelly.light-labs.dagster.plist

# Restart the daemon so it loads changed orchestration code
dagster-restart:
    launchctl kickstart -k gui/$(id -u)/com.pjkelly.light-labs.dagster

_dagster-home:
    mkdir -p var/dagster && cp ops/orchestration/dagster.yaml var/dagster/

# Definitions load, invariants hold, and a full run over the fixtures builds
dagster-check:
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    uv run --locked --group orchestration dagster definitions validate -m light_labs.orchestration 2>&1 | grep -q "Validation successful"
    uv run --locked --group orchestration python -m unittest tests.test_orchestration
