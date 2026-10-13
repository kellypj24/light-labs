# Same checks as CI. Run `just check` before pushing.

# profiles.yml lives in analytics/, not ~/.dbt
export DBT_PROFILES_DIR := justfile_directory() / "analytics"

default: check

# Pre-commit hooks (hygiene, ruff, zizmor, gitleaks) + unit tests
check: hooks test evals-check analytics-check beat-check

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

# Boss fight with real models. Runs locally only; one at a time on a laptop.
# Results land in var/evals/*.jsonl and are loaded into var/lab.duckdb.
# just eval reply-draft mega-man,bass 3
eval stage="reply-draft" contestants="mega-man" samples="3" *args="":
    status=0; go -C evals run . -stage {{stage}} -contestants {{contestants}} -samples {{samples}} {{args}} || status=$?; just analytics > /dev/null; exit $status

# Follow a fight live from a second terminal (default: the latest run)
watch run_id="":
    uv run --locked lab evals watch {{run_id}}

# Recent eval runs from marts.fct_eval_runs
runs *args="":
    uv run --locked lab evals runs {{args}}

# Approval queues: can a robot's draft kind skip approval yet?
queue *args="":
    uv run --locked lab queue status {{args}}

# Load var/evals and the robots' queues into var/lab.duckdb, then build the dbt project
analytics:
    uv run --locked lab evals ingest
    uv run --locked lab queue ingest
    cd analytics && uv run --locked --group analytics dbt build

# dbt lint and build on the synthetic fixtures in a throwaway database (same as CI)
analytics-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    LAB_VAR="$tmp" uv run --locked lab evals ingest analytics/fixtures/*.jsonl
    LAB_VAR="$tmp" uv run --locked lab queue ingest --root analytics/fixtures/queue
    cd analytics
    uv run --locked --group analytics sqlfluff lint models macros
    DUCKDB_PATH="$tmp/lab.duckdb" uv run --locked --group analytics dbt build --quiet
    cd ..
    uv run --locked --group analytics python -m unittest tests.test_dbt_model tests.test_autosend
    LAB_VAR="$tmp" uv run --locked lab evals runs

# Beat: Dagster UI and sensors over the analytics (http://127.0.0.1:3000). State in var/beat.
beat:
    mkdir -p var/beat && cp ops/beat/dagster.yaml var/beat/
    DAGSTER_HOME="$PWD/var/beat" uv run --locked --group beat dagster dev -m light_labs.beat

# Beat's definitions load, its invariants hold, and a full run over the fixtures builds
beat-check:
    cd analytics && uv run --locked --group beat dbt parse --quiet
    uv run --locked --group beat dagster definitions validate -m light_labs.beat 2>&1 | grep -q "Validation successful"
    uv run --locked --group beat python -m unittest tests.test_beat
