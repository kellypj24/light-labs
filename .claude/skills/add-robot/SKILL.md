---
name: add-robot
description: Commission a new robot in light-labs with its DLN number, package, persona, memory template, skills, tests and registry entry.
audience: [auto]
---

A robot has one job. Check that no existing robot already does it before adding one.

1. **Number it.** Take the next free number in `dln.json` (ours start at DLN-100; canon
   numbers are left alone). Name it after a Mega Man character that fits the job: support
   robots (Rush, Beat, Roll, Auto, Eddie) for infrastructure, robot masters for task
   specialists. Mega Man, Proto Man and Bass are reserved for the eval loop (see README).
2. **Register it** in `dln.json`: `dln`, `name`, `role`, `job`, `model` (`ollama:<tag>`),
   `actor` if it posts anywhere, `status` (`training` until its stage is earned, then
   `active`; support robots start `active`), `commissioned` date, `skills: []`,
   `weapons: []` (filled by the boss-fight skill's weapon get).
3. **Package** `light_labs/agents/<name>/`:
   - `__init__.py`: settings from the registry entry with env overrides (copy Rush's),
     `HOME = config.VAR / "<name>"`, `system_prompt(text)` built from persona + memory +
     `skills.render(...)`.
   - `persona.md`: character only, a few lines. Procedures belong in skills.
   - `memory.example.md`: template; the real `memory.md` is git-ignored.
   - the robot's behaviour module, taking its client, brain and store as arguments so
     tests can pass fakes.
4. **Skills.** List reused skills in `skills`. Write new ones under `.claude/skills/` with
   `audience`, and for robots `load` and `triggers`. Keep `always` skills short: they cost
   context on every call.
5. **CLI.** Add `lab <name> ...` subcommands in `light_labs/cli.py`.
6. **Tests** in `tests/test_<name>.py` with fake client and brain, no network or model.
7. **Schedule** only if PJ asks: copy the launchd plist in `ops/`.
8. README robot table, then the `lab-workflow` skill to ship it.
