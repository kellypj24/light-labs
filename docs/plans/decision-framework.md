# Plan: decision framework and the sensitivity gate

Status: approved with its spec, `docs/system-1-system-2.md`, in the same PR; no step started.
Written 2026-10-30.

Builds what the spec describes: a gate on every Claude call, then a Jev-style decision
framework on `decide.py` (calibration, named and score questions, routing rules, an
escalation stage). Each step is its own PR. Each step lists the files it touches; a change
to those files on `main` before the step starts means re-reading the step.

## Steps

1. **Sensitivity gate.** `light_labs/core/gate.py`: `check(source, system, user, tools,
   cwd)` returns allow, sanitize or deny, from fixed rules:
   - deny: content or `cwd` from client repos (recoup, dentasys-modernization), personal
     mail senders, `memory.md` content, unreleased-ideas paths;
   - repo tools (`tools`, `cwd`) only for repos on the allowlist;
   - each verdict is recorded (source, verdict, rule, no payload) for the marts.

   `ClaudeCLI.think` calls the gate and takes a required `source` (robot plus data kind).
   `tests/test_gate.py` fails when a module other than `brain.py` runs `claude` or builds
   `ClaudeCLI` without a source. Call sites to update: `agents/roll/chores.py`,
   `agents/roll/calibrate.py`, `agents/rush/__init__.py` (`AUTO_BRAIN`),
   `cli.py` (mail and keep teachers, `keep-fixtures`), `evals/run_one.py`,
   `evals/dbt_model.py` (Bass).
   Files: `light_labs/core/gate.py`, `light_labs/core/brain.py`, the call sites above,
   `tests/test_gate.py`.

2. **Calibration in core.** Generalise `agents/roll/calibrate.py` (per-question yes-bias
   baselines in `calibration.json`, Roll only) into `light_labs/core/calibrate.py`: an
   isotonic or Platt fit per brain and question on shadow pairs (local answer and Claude's
   on the same input; Roll's keep and chores records first). Fitted maps become a Dagster
   asset in DuckDB; `decide.ask` applies them read-only. `calibration.json` retires once
   Roll's writer reads the asset.
   Files: `light_labs/core/calibrate.py`, `light_labs/core/decide.py`,
   `light_labs/agents/roll/calibrate.py`, `light_labs/agents/roll/writer.py`,
   `light_labs/orchestration/`, `analytics/models/`.

3. **Named and score questions.** `decide.ask_many(brain, state, questions)` returns
   `answers.<name>`, sharing the cached prefix. A score question takes ordered labels; the
   answer is the probability-weighted position.
   Files: `light_labs/core/decide.py`, `tests/test_decide.py`.

4. **Routing rules.** `rules/<robot>.yaml`, read at runtime from the deployed release.
   `light_labs/core/rules.py` parses conditions over named answers (comparisons, `and`,
   `or`, `not`; no `eval`). Decision records name the rule that fired. Dagster loads the
   YAML as a dbt seed; marts give hit rate, agreement with Claude and missed escalations
   per rule. Roll's `mail-keep` escalation (roll-keep step 4b) is the first rule file.
   Files: `rules/`, `light_labs/core/rules.py`, `light_labs/agents/roll/keep.py`,
   `analytics/seeds/`, `analytics/models/`, `tests/test_rules.py`.

5. **Escalation stage.** Per robot, scored escalate vs handle; the costly miss is a case it
   should have escalated. Fixtures from shadow disagreements System 1 was confident on, at
   least 30 per stage.
   Files: `evals/stages/`, `evals/README.md`.

6. **Rule proposals.** System 2 proposals land in a DuckDB table through Dagster;
   `lab rules propose` lists them and opens a PR against `rules/<robot>.yaml` for the ones
   PJ accepts.
   Files: `light_labs/orchestration/`, `light_labs/cli.py`, `analytics/models/`.

When the last step lands, fold the result into the spec and archive this plan
(`plan-archive`).

## Decisions (PJ, 2026-10-30)

- Spec and plan split, Grove style; this PR approves both.
- Gate enforced in code, step 1, ahead of calibration.
- Rules authored in files, derived data in DuckDB (spec, Storage).
- No Grove CLI; no word budget for a single spec.
- Gate rollout: deny client repos from day one; every other rule records its verdict
  without blocking for two weeks, then enforces.
- Repo-tool allowlist: light-labs, data-engineering, scouter, claude-toolkit,
  temporal-echoes.
- Unreleased ideas: a path list per repo (`docs/plans/`, `STATUS.md`, design docs) in the
  gate's rules.
- Escalation stage: `Expect.label` with `escalate`/`handle`; no scorer change, so step 5
  drops `evals/scorer.go`.
- `agents/roll/sanitize.py` moves to `light_labs/core` when a second robot needs it.
