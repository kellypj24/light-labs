# Plan: decision framework and the sensitivity gate

Status: step 1 done 2026-10-30 (#91; `client-repo` denies, every other rule records until
2026-11-13); step 1b in review. Written 2026-10-30.

Builds what the spec describes: a gate on every Claude call, then a Jev-style decision
framework on `decide.py` (calibration, named and score questions, routing rules, an
escalation stage). Each step is its own PR. Each step lists the files it touches; a change
to those files on `main` before the step starts means re-reading the step.

## Steps

1. **Sensitivity gate.** `light_labs/core/gate.py`: `check(source, system, user, tools,
   cwd)` evaluates fixed rules, records the verdict, and raises `Denied` when an enforced
   rule denies. Rules (`ENFORCED` holds the ones that block):
   - `client-repo` (deny, enforced): `cwd` in, or text naming, recoup or
     dentasys-modernization;
   - `memory` (deny): the source carries `memory.md`;
   - `personal-mail` (sanitize): the source carries mail, or the text holds a
     personal-domain address;
   - `tool-repo` (deny): tools outside the allowlist;
   - `unreleased` (sanitize): tools in an allowed repo; once enforced, adds
     `--disallowedTools Read(./docs/plans/**),Read(./STATUS.md)`.

   `gate.SOURCES` maps each caller's source to what it carries. `ClaudeCLI` requires
   `source=`; `brain_for` refuses a `claude:` spec without one. `lab rush auto`, the one
   full Claude Code session, calls `gate.check` itself (`rush/auto-handoff`).
   `tests/test_gate.py` fails on a `claude` subprocess outside `brain.py` without
   `gate.check` in the same function, and on a `ClaudeCLI` or `brain_for` call without a
   known source. Verdicts go to `var/gate/verdicts.jsonl`; a Dagster asset loading them
   into the marts is a follow-up. `sanitize.py` moves to `light_labs/core` here.
   Files: `light_labs/core/gate.py`, `light_labs/core/brain.py`, `light_labs/core/sanitize.py`,
   `light_labs/cli.py`, `light_labs/agents/roll/{chores,calibrate,keep}.py`,
   `light_labs/evals/run_one.py`, `tests/test_gate.py`, `tests/test_sanitize.py`.

1b. **Rush through the sanitizer.** Before the window ends (2026-11-13): Rush's Auto
   prompt carries `memory.md` and its mail teacher carries real mail, personal senders
   included, so both would fail `memory` and `personal-mail` once enforced. Rush now:
   - mail teacher: labels only, from `sanitize.view`; personal mail and rule-filed bulk
     mail never reach it; summaries stay local, rewritten when the teacher's label moves
     mail into or out of `needs_reply`;
   - `lab rush queue`: the rewriter reads the sanitized view and skips personal mail;
   - Auto's notes: `sanitize.notes` drops `## Private` and scrubs the rest, dates kept;
     the gate's `memory` rule also fires on an unscrubbed `## Private` heading.

   Live check, 2026-10-30: 50 non-personal emails Sonnet had labelled on the full view,
   re-labelled on the sanitized view: 48/50 (bar 0.90). Misses: one `needs_reply` to
   `fyi`, one `receipt` to `fyi`.
   Still to do, in its own PR on 2026-11-13: add `memory`, `personal-mail`, `tool-repo`
   and `unreleased` to `ENFORCED` after reading `var/gate/verdicts.jsonl`.
   Files: `light_labs/core/sanitize.py`, `light_labs/agents/rush/mail.py`,
   `light_labs/cli.py` (`_auto`), `light_labs/core/gate.py`.

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
- `sanitize.py` moves to `light_labs/core` in step 1: Rush is the second robot (step 1b).
- Gate rules are constants in `gate.py`, not `rules/` (routing rules, step 4).
- `lab rush auto` stays a full Claude Code session, checked by the gate before launch.
- Step 1b: Rush's personal mail stays local; the teacher labels from the sanitized view and
  the local model writes every summary; `memory.md` leaves scrubbed with a `## Private`
  section that never leaves; board posts go to Auto as written; the mail rewriter reads the
  sanitized view.
