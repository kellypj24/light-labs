# light-labs

PJ's local AI lab. Robots (agents) run on local models; Claude Code is **Auto**, the lab's
mechanic, who builds and fixes things and takes work the robots escalate. Mega Man theme:
see README for the lore, `dln.json` for the robot registry.

## Skills

`.claude/skills/` is shared by Auto and the robots. Each `SKILL.md` declares an `audience`:
`auto` skills are for you; `robots` skills are loaded into robots' prompts (each robot's
`skills` list in `dln.json`). Read a robots skill before changing a robot's behaviour; it is
part of that robot's prompt. `lab skills` lists them all.

Start with `lab-workflow` before any commit, push or PR.

## Rules that matter here

- Never commit `.env`, `var/`, or any `memory.md`: they describe other people's systems.
- Robot memory goes stale fast; follow `update-robot-memory` after acting as a robot's actor.
- Robots on small models: keep their `always` skills short and test prompt changes against
  the live model, several samples per case, before shipping.
- `analytics/` follows `~/data-engineering/transformation/dbt`: one `.yml` per model,
  staging → intermediate → marts, sqlfluff rules from there (duckdb dialect). The marts
  decide weapons, so robot-written models never replace them without PJ's merge, and a
  robot is never scored by models it wrote.
- Naming: display names are canon ("Mega Man", "Guts Man"). Names of things we pick are
  kebab-case (stages, skills, contestants, roles, commands, branches: `mega-man`,
  `dbt-model`); code and keys inside things are snake_case (Python, SQL, fixture ids, data
  fields: `guts_man`, `select_harness_errors`, `run_id`).
- Rush's auto-send posts to other people's board as pj_agent. Loosen its guards, caps or
  kinds only when PJ asks, and say what changes.
- One heavy job at a time on PJ's laptop: never run `just check`, builds or a second fight
  while a local-model fight runs. Ask before starting a fight; say how long it takes. Run
  long local fights with `-cool-above 40`, and when one has to be stopped, record why
  (`lab evals cancel <run_id> --reason`).
- Checks: `just check` (same as CI). Details in `docs/ci-cd.md`.
