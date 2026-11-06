# Status

Current state only; history is in git and the PRs. Update this file in the same PR as the
work it describes.

_Updated 2026-11-06._

## Now

- Rush (DLN-100) live under launchd: hourly tick, board and mail triage, Telegram and the
  tailnet remote page. Escalations drafted by Auto, approved by PJ.
- Roll (DLN-102) live: Dependabot chores across PJ's repos (`lab roll chores`), mail
  cleanup, and the `mail-keep` weapon on `qwen2.5:14b`. Her chores answers now come from
  `qwen2.5:14b` too (`ROLL_CHORES_BRAIN` in `.env`).
- data-engineering Dependabot backlog (28 open) is Roll's chores training set: PJ runs
  `lab roll chores -C ~/data-engineering --apply --admin` daily until clear (one merge
  per directory per run, 10 a day); each run grows the record, `lab roll chores-fixtures`
  turns it into the `dependabot-merge` stage (24 fixtures from the record so far).
- Claude Code usage lands in `raw.claude_records` daily and feeds the `mart_claude_*`
  marts; credentials are redacted on ingest (#70).
- Hermes runs from `lab deploy` releases (`~/.hermes/lab/current`); `morning-brief` runs
  daily at 08:00 (`hermes cron list`).
- Heavy jobs (`just eval`, `lab roll keep`, `just check`) hold
  `~/.cache/light-labs/heavy.lock`, refuse a busy machine and stop on critical heat or
  memory; Dagster's sensors skip while it is held. `lab heavy status` before starting one;
  `lab heavy watch` or Rush's `/lab` page follow one live. Both list loaded Ollama
  models (size, time to unload): a model is wired memory and the usual cause of a pressure
  pause outside any heavy job (Rush's hourly mail triage loads `qwen2.5:14b`).
- Design principle for local vs paid models: `docs/system-1-system-2.md` (local first,
  sanitized escalation, full context only past two gates; harness, not training). Build
  plan: `docs/plans/decision-framework.md`. Step 1 live: a sensitivity gate on every
  Claude call; `client-repo` denies, other rules record to `var/gate/verdicts.jsonl`.
  Step 1b live: Rush's teacher labels from the sanitized view (48/50 against its
  full-view labels), personal mail stays local, Auto's notes leave scrubbed. On
  2026-11-13, read the verdicts and enforce the remaining rules. Step 2a (calibration
  maps per brain and question, `mart_calibration`) live; first real map, Roll's
  `deps` on `llama3.1:8b`, stays identity (raw p already calibrated). Step 2b in review:
  mail-keep keep pairs and `lab roll keep-replay`; the writer gates on calibrated p.
- Plans live in `docs/plans/<slug>.md`; finished ones move to
  `docs/archive/YYYY-MM-DD-<slug>.md` (claude-toolkit `plan-archive` skill).

## Next

1. Decision framework (`docs/plans/decision-framework.md`), where it stopped 2026-10-30:
   - Step 2b PR open (`feature/calibration-2b`): keep pairs, `lab roll keep-replay`,
     writer gate at 0.60 on calibrated p, `calibration.json` gone. Merge needs PJ.
   - Replay smoke (20 records, `qwen2.5:14b`): every keep p was 0.00 or 1.00, and 3 of
     13 at 1.00 were teacher discards; 9m42s for 20, mostly cooling pauses with the 14b
     loaded (memory pressure warn).
   - Step 2c proposed, not agreed (Open decisions below): Bayesian fits for small
     samples, ML over time for large ones.
   - 2026-11-13: read `var/gate/verdicts.jsonl`, then enforce `memory`, `personal-mail`,
     `tool-repo` and `unreleased` (its own PR).
   - `docs/plans/operational-store.md` (SQLite store) PR #95 open, not merged.
2. Roll keep-plan step 4: every `Roll/*` label shadow-labelled (200 each). Keep-vs-discard
   agreement: Social 190/200, Forums 136/200 (63 local keeps the teacher discards: group
   lists), Bulk 180/200; one lost keep (Forums). Step 4b started: `sanitize.py` (personal
   senders stay local, rule-based scrubber); `keep-fixtures` rewrites from it; the teacher
   is off by default. Next: run `keep-fixtures` (230 of 271 disagreements are
   non-personal), then the matchers and escalation rules (`docs/plans/roll-keep.md`).
3. `dependabot-merge` fight (mega-man, proto-14b, bass) once the backlog is through and
   the stage is re-generated; bar 0.95 and zero false yeses, per tier, patch first.
4. #71 Roll lands Auto's PRs by risk tier, shadow mode first.

## Open decisions

- Decision framework step 2c (`docs/plans/decision-framework.md`, Open questions 1-5):
  the fit ladder, credible intervals as an escalation signal, ship 2b before 2c, the full
  replay at `--limit 300` overnight, the commit-message fight after 2c.

- Dependabot PR #58 (dbt-core 1.12.6, dev only; no security alerts open).
- Eval storage: keep results indefinitely under `var/evals/<stage>/<run_id>.*` (today
  flat, ~4 MB) and prune `var/evals/cache/` (17 MB, rebuildable) past 30 days? Proposed,
  not agreed.

## Blocked on

Nothing.
