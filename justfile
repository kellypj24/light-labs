# Same checks as CI. Run `just check` before pushing.

# profiles.yml lives in analytics/, not ~/.dbt
export DBT_PROFILES_DIR := justfile_directory() / "analytics"

default: check

# Pre-commit hooks (hygiene, ruff, zizmor, gitleaks) + unit tests, as a heavy job
# (`lab heavy`: holds ~/.cache/light-labs/heavy.lock; waits up to 20 minutes for another
# heavy job or a busy machine, then refuses; a no-op in CI)
check:
    uv run --locked lab heavy run --wait 20 check -- just _check

# `test-all` runs every test module once; the two project checks then skip the modules
# they would run again on their own.
_check: pins hooks test-all evals-check-scoped (analytics-check "skip") (dagster-check "skip")

# Every project pinned to a Python version; Docker and CI agree with it (light_labs/pins.py)
pins:
    uv run --locked python -m light_labs.pins .

# Every pre-commit hook over every file, untracked ones included (--all-files skips them)
hooks:
    git ls-files -z --cached --others --exclude-standard | xargs -0 uvx pre-commit@4.6.2 run --show-diff-on-failure --files

test:
    uv run --locked python -m unittest discover -s tests -t .

# Every test module, the ones that need the analytics and orchestration groups included
test-all:
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    uv run --locked --group orchestration python -m unittest discover -s tests -t .

# Install the hooks so they run on every local commit
install-hooks:
    uvx pre-commit@4.6.2 install

# Auto-fix what ruff can, then format
fix:
    uvx ruff@0.17.0 check --fix .
    uvx ruff@0.17.0 format .

# evals-check when this branch changes a path in .github/eval-paths.txt: the question
# CI's Changes job asks of a PR. Committed, uncommitted and untracked files all count;
# with nothing changed against origin/main (or no origin/main) it runs.
evals-check-scoped:
    #!/usr/bin/env bash
    set -euo pipefail
    base=$(git merge-base HEAD origin/main 2>/dev/null) || base=""
    files=$( [ -z "$base" ] || { git diff --name-only "$base"; git ls-files --others --exclude-standard; } )
    if [ -z "$files" ] || echo "$files" | scripts/eval-paths.sh; then
        just evals-check
    else
        echo "evals-check skipped: nothing under .github/eval-paths.txt changed (CI skips it too)"
    fi

# Eval harness: format, vet, unit tests, and a smoke run against the mock contestant
evals-check:
    test -z "$(gofmt -l evals)" || (gofmt -l evals && exit 1)
    go -C evals vet ./...
    go -C evals test ./...
    go -C evals run . -concurrency 4 -contestants mock -samples 1 -out "$(mktemp -d)" > /dev/null
    # dbt-model's mock answers with each reference: every reference must build and match
    go -C evals run . -concurrency 4 -stage dbt-model -contestants mock -samples 1 -min-pass 1 -out "$(mktemp -d)" > /dev/null
    # commit-message's mock answers with each reference: every reference must pass every check
    go -C evals run . -concurrency 4 -stage commit-message -contestants mock -samples 1 -min-pass 1 -out "$(mktemp -d)" > /dev/null
    # mail-keep wiring: every fixture loads and runs (the mock answers no class: keep/unsure)
    go -C evals run . -concurrency 4 -stage mail-keep -contestants mock -samples 1 -out "$(mktemp -d)" > /dev/null

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
    DAGSTER_HOME="${LAB_VAR:-$PWD/var}/dagster" uv run --locked --group orchestration dagster job execute -m light_labs.orchestration -j analytics_job

# dbt lint and build on the synthetic fixtures in a throwaway database (same as CI)
analytics-check tests="run":
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    LAB_VAR="$tmp" uv run --locked lab evals ingest analytics/fixtures/*.jsonl
    LAB_VAR="$tmp" uv run --locked lab queue ingest --root analytics/fixtures/queue
    LAB_VAR="$tmp" uv run --locked lab claude ingest --projects analytics/fixtures/claude/projects
    LAB_VAR="$tmp" uv run --locked --group analytics lab calibration ingest --root analytics/fixtures/calibration
    LAB_VAR="$tmp" uv run --locked lab training ingest-strong analytics/fixtures/strong/strong-2026-11-01.csv
    LAB_VAR="$tmp" uv run --locked lab training ingest-health analytics/fixtures/health/*.json
    LAB_VAR="$tmp" uv run --locked lab training ingest-notes analytics/fixtures/training/notes.jsonl
    LAB_VAR="$tmp" uv run --locked lab training ingest-plans analytics/fixtures/training/plans/*.json
    cd analytics
    uv run --locked --group analytics sqlfluff lint models macros
    DUCKDB_PATH="$tmp/lab.duckdb" uv run --locked --group analytics dbt build --quiet
    cd ..
    if [ "{{tests}}" = run ]; then
        uv run --locked --group analytics python -m unittest tests.test_dbt_model tests.test_autosend tests.test_commit_message tests.test_calibrate
    fi
    LAB_VAR="$tmp" uv run --locked lab evals runs

# Dagster UI (http://127.0.0.1:3000). The sensors run in the daemon, not here.
dagster: _dagster-home
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    DAGSTER_HOME="${LAB_VAR:-$PWD/var}/dagster" uv run --locked --group orchestration dagster-webserver -m light_labs.orchestration -p 3000

# The daemon that ticks the sensors; launchd runs this (ops/com.pjkelly.light-labs.dagster.plist)
dagster-daemon: _dagster-home
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    DAGSTER_HOME="${LAB_VAR:-$PWD/var}/dagster" exec uv run --locked --group orchestration dagster-daemon run -m light_labs.orchestration

# Install (or reinstall) Roll's daily Dependabot chores (17:30) as a launchd job
roll-chores-install: (_reload "roll-chores")

# Unload a launchd job, wait until launchd has let go of it (loading at once fails with
# "Bootstrap failed: 5" for a KeepAlive job), copy its plist from ops/ and load it
_reload job:
    #!/usr/bin/env bash
    set -euo pipefail
    label=com.pjkelly.light-labs.{{job}}
    domain=gui/$(id -u)
    launchctl bootout "$domain/$label" 2>/dev/null || true
    for _ in $(seq 40); do
        launchctl print "$domain/$label" >/dev/null 2>&1 || break
        sleep 0.5
    done
    cp "ops/$label.plist" ~/Library/LaunchAgents/
    launchctl bootstrap "$domain" ~/Library/LaunchAgents/"$label.plist"

# Install (or reinstall) Rush's heartbeat and phone page as launchd jobs
rush-install: (_reload "rush") (_reload "rush-remote")

# Install (or reinstall) and start the daemon's launchd job
dagster-install: _dagster-home (_reload "dagster")

# Restart the daemon so it loads changed orchestration code
dagster-restart:
    launchctl kickstart -k gui/$(id -u)/com.pjkelly.light-labs.dagster

# Pause scheduled jobs: rush (hourly tick, default), rush-remote (phone page), dagster,
# hermes (gateway and its crons, e.g. morning-brief), radar (Messages export, sync,
# weekly), or all. Nothing is lost: each catches up on its next run. `just resume`
# starts them again; `just bots` shows which run.
pause +jobs="rush":
    @scripts/bots.sh pause {{ jobs }}

resume +jobs="rush":
    @scripts/bots.sh resume {{ jobs }}

bots:
    @scripts/bots.sh status all

# var/ is the checkout's, or LAB_VAR's when a deployed release runs these recipes
_dagster-home:
    mkdir -p "${LAB_VAR:-var}/dagster" && cp ops/orchestration/dagster.yaml "${LAB_VAR:-var}/dagster/"

# Definitions load, invariants hold, and a full run over the fixtures builds
dagster-check tests="run":
    cd analytics && uv run --locked --group orchestration dbt parse --quiet
    uv run --locked --group orchestration dagster definitions validate -m light_labs.orchestration 2>&1 | grep -q "Validation successful"
    [ "{{tests}}" != run ] || uv run --locked --group orchestration python -m unittest tests.test_orchestration
