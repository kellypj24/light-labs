---
name: boss-fight
description: Design an eval stage (a "boss fight") for a task class, so a local model can earn the weapon for it. Use when adding or changing anything under evals/.
audience: [auto]
---

A stage answers one question: is a local model good enough at this task class to stop
paying a cloud model for it? `evals/README.md` has the harness layout and commands.

Mechanics: a stage is `evals/stages/<stage>.yaml` (+ `<stage>.memory.md` if the robot
needs memory) and a function in `light_labs/evals/run_one.py` `STAGES` that runs one
input through the robot's real pipeline. Reuse the robot's own prompt builders; never
copy them, or the eval measures something the robot doesn't run. Smoke-test with
`go -C evals run . -stage <stage> -contestants mock -samples 1`.

1. **Pick one task class** a robot actually does (for example `reply-draft`). One stage
   per class.
2. **Fixtures**: at least 30 before reading anything into the numbers. Model them on real
   traffic, including what PJ approved or rejected, but the repo is public: rewrite them
   with synthetic names and content.
3. **Checks, deterministic first**: format, length, required escalation, no invented past
   work, no promises of undecided work. Code checks anything code can check.
4. **Judge second**, only for what code can't check, with a pinned rubric and model.
5. **Contestants**: Mega Man (best local model), Proto Man (the challenger model), Bass (the
   cloud baseline). Record score, latency and cost per fixture for each.
6. **Bar**: before the first run, write `bar:` in the stage YAML: `min_fixture_rate`,
   `max_gap` and a one-sentence `reason`. The runner records it on every sample and
   `mart_weapon_status` judges each run by the bar it was made under, so a later change
   never rewrites a past verdict.
   - The measure is the **fixture** pass rate: a fixture counts only if every sample
     passed. Mega Man runs 3 samples and Bass 1, so this is stricter for local, on purpose.
   - Start at the lab default: floor 0.90, gap 0.05 (`weapon_*` vars in
     `analytics/dbt_project.yml`).
   - Raise the floor when a wrong output acts without review (posts, merges, spends).
     Lower it only for output PJ reviews before it leaves the lab, and only on his say.
   - The gap is a fixed delta, not cost-weighted. A local model's marginal cost is near
     zero, so weighting by cost would always pick local; cost decides which stage is worth
     building, the bar protects quality.
   - Bass runs the same full fixture set. No Bass run, no weapon.
   - Change a bar in its own commit, never alongside the prompt changes it would flatter.
7. **Where it runs**: locally (launchd or by hand), never in CI. CI tests only the
   harness wiring, with fakes.
8. **Weapon get**: `marts.mart_weapon_status` says which stages are earned. The weapon goes
   on the stage's robot master in `dln.json`, not on Mega Man (who has no entry; he is the
   local brain slot): set the robot's `model` to the brain that earned it, `status` to
   `active`, and add `{"stage", "brain", "run_id", "earned"}` to its `weapons`. The robot
   master is still what gets invoked; it now runs locally instead of escalating. Routing
   is per stage: if Proto Man's brain later beats Mega Man's on one stage, only that
   robot switches.
