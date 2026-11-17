# CI/CD

What runs, why, and what is deliberately left out. Modelled on `data-engineering`'s
hardening plan, sized for a small public repo with one owner.

## Local == CI

`just check` runs the same pre-commit hooks, unit tests and eval-harness checks as CI, at the same versions.
It runs every test module once (`just test-all`, with the analytics and orchestration
groups), so `analytics-check` and `dagster-check` skip the modules they run when called
on their own. The mock eval runs use `-concurrency 4`, here and in CI; fights keep 1.
Like CI, it runs the eval-harness checks only when the branch changes a path in
`.github/eval-paths.txt` (`scripts/eval-paths.sh` answers for both); `just evals-check`
runs them regardless. When another heavy job holds the lock or the machine is busy, `just check` waits up to
20 minutes for it (`lab heavy run --wait 20 check`) and then refuses; it never waits out work
hours, and a kill switch stopping a running check is still a failure.
`just install-hooks` makes them run on every commit. A hook that would rewrite a file fails
instead of fixing, so CI can't pass on an auto-fix.

| Hook | Catches |
|---|---|
| pre-commit-hooks | trailing whitespace, missing EOF newline, bad YAML/TOML/JSON, merge markers, files over 512 KB, private keys |
| ruff (check + format --check) | lint and formatting |
| zizmor | insecure GitHub Actions workflows: template injection, over-broad permissions, credential persistence |
| never-committed | a staged path under `var/`, a `.env`, a `memory.md` or a DuckDB file (`lab git ship` stages with `git add -A`) |
| gitleaks | secrets anywhere in git history, via `scripts/gitleaks.sh` (pinned version, pinned SHA-256) |

## Workflow (`.github/workflows/ci.yml`)

| Job | Runs |
|---|---|
| Hooks | `pre-commit run --all-files` over the full history |
| Tests | unit tests on Python 3.12 and 3.13, `uv sync` with `UV_LOCKED=1` so a stale `uv.lock` fails |
| Changes | which gated jobs a PR needs: the files it changes against `.github/eval-paths.txt` |
| Eval harness | `gofmt`, `go vet`, `go test`, and a smoke run of the `reply-draft` stage against the `mock` contestant (fails only if a sample could not run). On PRs, only when a listed path changed; `tests/test_ci_paths.py` fails if an eval stage imports a module the list misses |
| Analytics (dbt) | sqlfluff, then ingest the synthetic fixtures and `dbt build` every model, data test and unit test |
| Orchestration (Dagster) | `dbt parse`, `dagster definitions validate`, `tests/test_orchestration.py` (invariants, sensor logic, the analytics job over the fixtures) |
| CI Success | fan-in: the single required check; fails if any job failed or was cancelled |

Triggers: PRs into `main`, every push to `main` (a post-merge backstop, runs every job), manual dispatch.

Hardening applied to every workflow:
- Actions pinned to full commit SHAs, version in a trailing comment. A re-pointed tag can't
  change what runs.
- `permissions: {}` at the top; jobs request only `contents: read`.
- `persist-credentials: false` on checkout, so the token isn't left in `.git/config`.
- Untrusted values reach `run:` through `env:`, never inline `${{ }}`.
- uv caching off: a cache is one more thing to poison. The orchestration (Dagster) group is the largest
  sync, at well under a minute.
- `timeout-minutes` on every job; superseded PR runs are cancelled.

## Python version (`.python-version`, `light_labs/pins.py`)

`.python-version` pins the interpreter (major.minor) for uv, CI and every worktree;
`requires-python` stays the supported floor. `just pins` (part of `just check`, and a step
in the Tests job) fails when a `pyproject.toml` has no pin above it, the pin falls outside
`requires-python`, a Dockerfile's Python differs from it (unless the line above its `FROM`
says `# pin-exempt: <reason>`), or a workflow names a Python that is neither the pin, the
floor nor the next minor. It warns about end-of-life versions, a pin two minors behind the
newest stable, and a floor nothing runs.

`lab python status --all` runs the same audit over every checkout in `~` and flags a
repo's own copy (`.github/scripts/check_python_pins.py`, for repos that can't depend on
the lab) that has drifted from `light_labs/pins.py`.

Moving the pin: `python-next.yml` runs the unit tests weekly on the minor after the pin.
When it is green, change `.python-version`, `uv lock`, and the CI matrix in one PR.

## Deploys (`lab deploy`, `light_labs/deploy.py`)

Nothing scheduled runs the checkout. Each target is a directory of releases, one per
commit of `origin`, exported with `git archive` and installed with `uv sync --locked`;
`current` points at the live one and the last 3 are kept.

| Target | Runs | Restart on a new commit |
|---|---|---|
| `lab` (`~/.light-labs/lab`) | Rush's hourly tick and phone page, the Dagster daemon, Roll's chores (`ops/*.plist`) | The phone page; the Dagster daemon unless a run is in progress. The tick and chores are a new process each time |
| `hermes` (`~/.hermes/lab`) | Hermes's lab MCP server | `hermes gateway restart` |
| `radar` (docs/radar.md) | Radar's scheduled sync and digest | none |

The `lab` jobs start `current/.venv/bin/lab` itself (its shebang names that release's
interpreter). `uv run --project <target>/current` is not safe there: uv caches the
interpreter it found at that path and goes on starting the release before; Hermes's
`--directory` resolves the link first and is unaffected. The `lab` jobs set `LAB_VAR` to the checkout's `var/`, so data, logs and `var/lab.duckdb`
stay where they were; `.env` and Rush's `memory.md` are linked from the main checkout.
A branch open in the checkout, or a merge not yet deployed, never reaches a service.

After a merge `lab git land` waits for CI's push run on the merge commit (the post-merge
backstop) and then redeploys every target on `main` to that commit, not to whatever
`main` has reached since. Red, cancelled (a newer merge replaced a queued run) or
missing CI deploys nothing and exits non-zero, as does a failed deploy; a target already
at or past the commit is left. `--no-wait` skips both waits. `lab deploy <target> --ref <branch>` tries a branch; `lab deploy <target> --rollback`
goes back to the release before the current one, until the next deploy.

Changing a plist: `just rush-install`, `just roll-chores-install`, `just dagster-install`
or `just ollama-install` copies it from the checkout and reloads the job. The Ollama job
runs Ollama.app's own `ollama serve`, not a release, so a deploy never touches it.

## Claude review (`claude-code-review.yml`, `claude.yml`)

| Workflow | Runs |
|---|---|
| Claude Code Review | on PR open and each push: the `code-review` plugin posts inline comments. Skips Dependabot (no secrets there) and drafts; one run per PR, a new push cancels the last |
| Claude Code | an `@claude` mention in a PR comment or review, from someone with write access. Asked for a change, it can commit to the PR branch through the app's token (accepted 2026-10-28); it cannot merge, and `main` takes changes only by PR with CI Success |

Advisory: neither is a required check or part of CI Success. Auth is the
`CLAUDE_CODE_OAUTH_TOKEN` secret (PJ's subscription); the Claude GitHub App's token posts
the comments, via `id-token: write`. The review plugin comes from the
`anthropics/claude-code` marketplace at its default branch, not pinned.

## Repository settings (`ops/github-settings.sh`)

Idempotent; re-run after changing it.
- Ruleset on `main`, **no bypass actors**: changes arrive by PR, `CI Success` must pass, no
  force-push or deletion. Not even an admin merge lands a red CI.
- Squash merges only, PR title as the commit title; branches deleted on merge.
- Secret scanning with push protection, Dependabot alerts and security updates, CodeQL
  default setup (Python + Actions).

## Dependencies (`.github/dependabot.yml`)

Weekly, grouped, with a 7-day cooldown on every ecosystem (github-actions, uv, and gomod for `evals/`): a release has to have been public
for a week before it is proposed. `github-actions` keeps the SHA pins current; `uv` moves
`uv.lock` with `pyproject.toml`.

## Pushing from Claude Code

`~/.claude/hooks/pre-push-check.sh` blocks pushes from Claude sessions. This repo opted in
(`git config claude.prepushAck true`), so a push prefixed with `PREPUSH_ACK=1` is allowed
once `just check` has passed on the current tree. Clones don't inherit the opt-in.

## Deliberately not added (yet)

| Item | Add when |
|---|---|
| Scheduled `pip-audit` tracker issue | The project has third-party runtime dependencies (today it is stdlib only; Dependabot alerts cover the lockfile) |
| Type checking (`ty` or `mypy`) | The code grows past a few modules or starts taking typed external data |
| Real-model evals in CI | Never on hosted runners (7 GB RAM; scores meaningless on mocks) and **never on a self-hosted runner**, because this repo is public and fork PRs could run code on it. Boss fights run locally on launchd; CI tests wiring only. |
| Claude PR review | An `ANTHROPIC_API_KEY` secret is worth it; the workflow must skip cleanly without it |
| Semantic PR titles, auto-labels, stale bot | There are other contributors |
| Release automation | The lab ships versioned artifacts |
