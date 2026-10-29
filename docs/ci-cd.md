# CI/CD

What runs, why, and what is deliberately left out. Modelled on `data-engineering`'s
hardening plan, sized for a small public repo with one owner.

## Local == CI

`just check` runs the same pre-commit hooks, unit tests and eval-harness checks as CI, at the same versions.
`just install-hooks` makes them run on every commit. A hook that would rewrite a file fails
instead of fixing, so CI can't pass on an auto-fix.

| Hook | Catches |
|---|---|
| pre-commit-hooks | trailing whitespace, missing EOF newline, bad YAML/TOML/JSON, merge markers, files over 512 KB, private keys |
| ruff (check + format --check) | lint and formatting |
| zizmor | insecure GitHub Actions workflows: template injection, over-broad permissions, credential persistence |
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
