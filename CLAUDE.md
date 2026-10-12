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
- Checks: `just check` (same as CI). Details in `docs/ci-cd.md`.
