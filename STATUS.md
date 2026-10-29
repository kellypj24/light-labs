# Status

Current state only; history is in git and the PRs. Update this file in the same PR as the
work it describes.

_Updated 2026-10-28._

## Now

- Rush (DLN-100) live under launchd: hourly tick, board and mail triage, Telegram and the
  tailnet remote page. Escalations drafted by Auto, approved by PJ.
- Roll (DLN-102) live: Dependabot chores across PJ's repos (`lab roll chores`), mail
  cleanup, and the `mail-keep` weapon on `qwen2.5:14b`.
- Claude Code usage lands in `raw.claude_records` daily and feeds the `mart_claude_*`
  marts; credentials are redacted on ingest (#70).
- Hermes runs from `lab deploy` releases (`~/.hermes/lab/current`); `morning-brief` runs
  daily at 08:00 (`hermes cron list`).
- Heavy jobs (`just eval`, `lab roll keep`, `just check`) hold
  `~/.cache/light-labs/heavy.lock`, refuse a busy machine and stop on critical heat or
  memory; Dagster's sensors skip while it is held. `lab heavy status` before starting one;
  `lab heavy watch` or Rush's `/lab` page follow one live.
- Plans live in `docs/plans/<slug>.md`; finished ones move to
  `docs/archive/YYYY-MM-DD-<slug>.md` (claude-toolkit `plan-archive` skill).

## Next

1. Roll keep-plan step 4: every `Roll/*` label shadow-labelled (200 each). Teacher
   agreement: Social 78%, Forums 48%, Bulk 79%; discards the teacher would keep: Social 0,
   Forums 1 (a personal reply in a group-list thread), Bulk 0. Next: turn the
   disagreements into fixtures (`lab roll keep-fixtures`), Forums first, then step 4b,
   sanitized escalation (`docs/plans/roll-keep.md`).
2. #71 Roll lands Auto's PRs by risk tier, shadow mode first.

## Open decisions

- Dependabot PR #58 (dbt-core 1.12.6, dev only; no security alerts open).
- Eval storage: keep results indefinitely under `var/evals/<stage>/<run_id>.*` (today
  flat, ~4 MB) and prune `var/evals/cache/` (17 MB, rebuildable) past 30 days? Proposed,
  not agreed.

## Blocked on

Nothing.
