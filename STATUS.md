# Status

Current state only; history is in git and the PRs. Update this file in the same PR as the
work it describes.

_Updated 2026-11-10._

## Now

- PJ uses this 16 GB MacBook for work (Teams, Memex) until an always-on Mac mini takes
  the local models; Claude Code is on a Max plan. Work hours (`LAB_WORK_HOURS`, weekdays
  08:00-17:00, `core/workhours.py`): no local model loads, heavy jobs other than
  `just check` need `--force`, Roll sits out of chores (big brother decides alone). Rush
  drafts and triages through `RUSH_WORK_BRAIN` (`claude:sonnet`), drafts all queued;
  personal mail waits for 17:00. Outside work hours each local model unloads when its
  step ends. Rush ticks at :07. `RUSH_MAIL_MODEL=llama3.1:8b` in `.env` meanwhile (one
  ~5 GB model per tick instead of 8b + 14b).
- Rush (DLN-100) live under launchd: hourly tick, board and mail triage, Telegram and the
  tailnet remote page. Escalations drafted by Auto, approved by PJ. muse's LOOP thread
  (`task_fb2e059c5a8bd362`) muted 2026-11-09: 73 of ~88 drafts since 11-03, all rejected.
  The daily ask digest lists held asks only, not ones Auto noted.
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
  memory; Dagster's sensors skip while it is held. A container VM blocks only above 50%
  CPU, so an idle Docker Desktop doesn't. `lab heavy status` before starting one;
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
  maps per brain and question, `mart_calibration`) in review; first real map, Roll's
  `deps` on `llama3.1:8b`, stays identity (raw p already calibrated). 2b replays mail-keep.
- Relationship Radar (`light_labs/radar`, `lab radar`, docs/radar.md) live on real data
  since 2026-11-08: a Swift helper (the only code with Full Disk Access, built only from
  source PJ approved) exports Messages and the Mac's Contacts at 06:20; `sync` 06:30
  daily, `weekly` Friday 15:00 (LaunchAgents) → `~/.relationship-radar`. First sync:
  39.5k interactions, 160 people. Gate rule `radar` denies its data to Claude.
- Plans live in `docs/plans/<slug>.md`; finished ones move to
  `docs/archive/YYYY-MM-DD-<slug>.md` (claude-toolkit `plan-archive` skill).

## Next

1. Roll keep-plan step 4: every `Roll/*` label shadow-labelled (200 each). Keep-vs-discard
   agreement: Social 190/200, Forums 136/200 (63 local keeps the teacher discards: group
   lists), Bulk 180/200; one lost keep (Forums). Step 4b started: `sanitize.py` (personal
   senders stay local, rule-based scrubber); `keep-fixtures` rewrites from it; the teacher
   is off by default. Next: run `keep-fixtures` (230 of 271 disagreements are
   non-personal), then the matchers and escalation rules (`docs/plans/roll-keep.md`).
2. `dependabot-merge` fight (mega-man, proto-14b, bass) once the backlog is through and
   the stage is re-generated; bar 0.95 and zero false yeses, per tier, patch first.
3. #71 Roll lands Auto's PRs by risk tier, shadow mode first.
4. Radar: Rush delivers the weekly picks (Telegram), the first robot tie-in. Slice 2
   LinkedIn export, slice 3 Gmail (`gmail.metadata`) and Calendar (`calendar.readonly`),
   asked before requesting scopes.
5. Training planner (`docs/plans/training.md`): steps 1–5 live (landing, marts,
   context, `lab training plan`). Step 6 in review: Rush's hourly tick sends next week's
   plan Sunday evening, asks for stale Strong or Health files, refreshes the plan when a
   requested one lands, `/replan` on demand. Work calendar not shared yet (weekdays
   08:00–17:00 assumed busy). The Claude desktop task keeps planning until two lab plans
   in a row pass review; then it's retired.

## Open decisions

- Work-hours board drafts from Claude always queue for PJ (auto-send was earned by
  `llama3.1:8b`). Let them auto-send under the same guards? Not decided.
- `OLLAMA_MAX_LOADED_MODELS=1` is set with `launchctl setenv`, which a reboot clears;
  make it permanent (a LaunchAgent that sets it at login) or drop it once the Mac mini
  runs Ollama?
- Radar's shared digest goes to Google Drive for Desktop, which isn't installed; until it
  is, `lab radar weekly` writes the local copy only.

- Dependabot PR #58 (dbt-core 1.12.6, dev only; no security alerts open).
- Eval storage: keep results indefinitely under `var/evals/<stage>/<run_id>.*` (today
  flat, ~4 MB) and prune `var/evals/cache/` (17 MB, rebuildable) past 30 days? Proposed,
  not agreed.

## Blocked on

Nothing.
