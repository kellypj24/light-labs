---
name: boss-fight
description: Design an eval stage (a "boss fight") for a task class, so a local model can earn the weapon for it. Use when adding or changing anything under evals/.
audience: [auto]
---

A stage answers one question: is a local model good enough at this task class to stop
paying a cloud model for it? See `evals/README.md` for the stage list.

1. **Pick one task class** a robot actually does (for example `reply-draft`). One stage
   per class.
2. **Fixtures**: real inputs, at least 30 before reading anything into the numbers. Take
   them from real traffic, and record what PJ approved or rejected as ground truth.
3. **Checks, deterministic first**: format, length, required escalation, no invented past
   work, no promises of undecided work. Code checks anything code can check.
4. **Judge second**, only for what code can't check, with a pinned rubric and model.
5. **Contestants**: Rock (best local model), Proto Man (the challenger model), Bass (the
   cloud baseline). Record score, latency and cost per fixture for each.
6. **Bar**: decide before running what "close enough to Bass" means for this class.
7. **Where it runs**: locally (launchd or by hand), never in CI. CI tests only the
   harness wiring, with fakes.
8. **Weapon get**: when Rock clears the bar, add the class to his `weapons` in `dln.json`
   and route that work local.
